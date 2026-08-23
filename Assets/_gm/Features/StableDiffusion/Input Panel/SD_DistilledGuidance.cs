using System;
using System.IO;
using UnityEngine;

namespace spz {

	// Flux-family checkpoints are *guidance-distilled*: the effect of CFG is already
	// baked into the weights, and they read a guidance value straight from a
	// conditioning embedding instead. Forge exposes that as 'distilled_cfg_scale',
	// a separate field from the classic 'cfg_scale'.
	//
	// Sending our usual cfg_scale to one of them costs us twice:
	//   - webui runs the real two-pass CFG, so every generation takes twice as long
	//   - guidance lands on top of guidance, so colours burn out
	//
	// So for those checkpoints we send cfg_scale=1 (which is what turns the second
	// pass off) and pass the user's slider value through as distilled_cfg_scale.
	//
	// Detection is by checkpoint name, because neither A1111 nor Forge report a model
	// architecture anywhere under /sdapi/v1. That is a guess, so it can be turned off:
	// put '--no-distilled-cfg' in spz.config to always send cfg_scale, as before.
	public static class SD_DistilledGuidance {

	    public const string DISABLE_FLAG = "--no-distilled-cfg";

	    // Lowercase substrings that identify a guidance-distilled checkpoint.
	    // Deliberately narrow - a false positive silently changes how a model
	    // generates, which is worse than missing a rename nobody uses.
	    static readonly string[] _distilled_markers = {
	        "flux1", "flux-1", "flux.1", "flux_1",
	        "flux2", "flux-2", "flux.2", "flux_2",
	    };

	    static bool _readConfig_already = false;
	    static bool _disabled_byConfig = false;


	    public static bool isDistilled_checkpoint(string modelName){
	        if(string.IsNullOrEmpty(modelName)){ return false; }
	        string lower = modelName.ToLowerInvariant();
	        foreach(string marker in _distilled_markers){
	            if(lower.Contains(marker)){ return true; }
	        }
	        return false;
	    }


	    // What webui says it currently has loaded. Preferred over our dropdown because
	    // the dropdown can briefly disagree right after the user picks a new model.
	    public static string currentCheckpoint_name(){
	        var fetcher = SD_Options_Fetcher.instance;
	        var opts = fetcher==null ? null : fetcher.currentOptions;
	        if(opts!=null  &&  string.IsNullOrEmpty(opts.sd_model_checkpoint)==false){
	            return opts.sd_model_checkpoint;
	        }
	        var models = SD_Neural_Models.instance;//scenes may still be loading.
	        return models==null ? "" : models.selectedModel_name;
	    }


	    public static bool isDistilled_active()
	        => isDisabled_byConfig()==false  &&  isDistilled_checkpoint( currentCheckpoint_name() );


	    // Fills in the two guidance fields for whichever checkpoint is loaded right now.
	    // 'sliderValue' is what the user dialled into the CFG slider.
	    public static void Apply(float sliderValue,  ref float cfg_scale_,  ref float? distilled_cfg_scale_)
	        => Apply( sliderValue, isDistilled_active(), ref cfg_scale_, ref distilled_cfg_scale_ );


	    // Same, but told outright which kind of checkpoint we are talking to, instead of
	    // asking the singletons. Keeps the decision testable without a loaded scene.
	    public static void Apply(float sliderValue,  bool isDistilled,
	                             ref float cfg_scale_,  ref float? distilled_cfg_scale_){
	        if( isDistilled == false ){
	            cfg_scale_ = sliderValue;
	            distilled_cfg_scale_ = null;//stays out of the JSON entirely.
	            return;
	        }
	        cfg_scale_ = 1f;                    //1 is what disables webui's two-pass CFG.
	        distilled_cfg_scale_ = sliderValue;
	    }


	    static bool isDisabled_byConfig(){
	        if(_readConfig_already){ return _disabled_byConfig; }
	        _readConfig_already = true;
	        _disabled_byConfig  = ReadConfigFlag(DISABLE_FLAG);
	        return _disabled_byConfig;
	    }

	    // Same file and lookup rule as CheckForUpdates_MGR, so users keep one place
	    // to configure the app.
	    static bool ReadConfigFlag(string flag){
	        try{
	            string exeDir = Directory.GetParent(Application.dataPath).FullName;
	            string configPath = Path.Combine(exeDir, CheckForUpdates_MGR.CONFIG_FILENAME);
	            if(File.Exists(configPath) == false){ return false; }
	            foreach(string line in File.ReadAllLines(configPath)){
	                if(line.Trim().Equals(flag, StringComparison.OrdinalIgnoreCase)){ return true; }
	            }
	        }catch(Exception){
	            //an unreadable config must never stop a generation.
	        }
	        return false;
	    }
	}
}//end namespace

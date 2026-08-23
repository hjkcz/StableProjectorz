using NUnit.Framework;
using Newtonsoft.Json;
using System.Collections.Generic;

namespace spz.Tests {

	// Covers the Flux guidance handling: which checkpoints get recognised, what the two
	// guidance fields end up as, and - most importantly - that a non-Flux request still
	// serialises exactly as it did before the field existed.
	//
	// These live in an 'Editor' folder without an asmdef on purpose: an asmdef cannot
	// reference Assembly-CSharp (Unity compiles it last), so this is the only way for a
	// test to see the 'spz' classes. Run via Window > General > Test Runner > EditMode.
	public class SD_DistilledGuidance_Tests {

	    // The serializer settings that SD_Generate_NetworkSender actually posts with.
	    static JsonSerializerSettings SenderSettings() => new JsonSerializerSettings{
	        Formatting = Formatting.Indented,
	        TypeNameHandling = TypeNameHandling.Auto,
	    };


	// ---------- which checkpoints count as guidance-distilled ----------

	    [TestCase("flux1-dev.safetensors")]
	    [TestCase("flux1-dev-bnb-nf4-v2.safetensors [821e0d1f0f]")]
	    [TestCase("flux1-schnell-fp8")]
	    [TestCase("flux.1-dev")]
	    [TestCase("flux-1-dev")]
	    [TestCase("flux_1_dev")]
	    [TestCase("FLUX1-DEV.SAFETENSORS")]          //webui reports names as-is, casing varies.
	    [TestCase("flux2-klein-4B.safetensors")]
	    [TestCase("FLUX.2-klein-9B")]
	    [TestCase("myFolder/flux1-dev.safetensors")] //checkpoints can sit in subfolders.
	    public void Recognises_flux_checkpoints(string modelName){
	        Assert.IsTrue( SD_DistilledGuidance.isDistilled_checkpoint(modelName),
	                       $"'{modelName}' should have been detected as guidance-distilled" );
	    }


	    [TestCase("sd_xl_base_1.0.safetensors")]
	    [TestCase("juggernautXL_v9Rundiffusion.safetensors")]
	    [TestCase("realisticVisionV51_v51VAE.safetensors")]
	    [TestCase("v1-5-pruned-emaonly.safetensors")]
	    [TestCase("sd3.5_large.safetensors")]        //SD 3.5 uses real CFG, must not be caught.
	    [TestCase("")]
	    [TestCase(null)]
	    public void Leaves_other_checkpoints_alone(string modelName){
	        Assert.IsFalse( SD_DistilledGuidance.isDistilled_checkpoint(modelName),
	                        $"'{modelName}' should NOT have been detected as guidance-distilled" );
	    }


	    // The markers require a version digit, so an unrelated model that merely has
	    // 'flux' in its name keeps the normal CFG path. This is the deliberate narrowness
	    // of the heuristic - a false positive silently changes how a model generates.
	    [TestCase("fluxion_xl_v2.safetensors")]
	    [TestCase("afluxofcolour.safetensors")]
	    public void Does_not_catch_unrelated_names_containing_flux(string modelName){
	        Assert.IsFalse( SD_DistilledGuidance.isDistilled_checkpoint(modelName),
	                        $"'{modelName}' is not a Flux checkpoint and must keep plain cfg_scale" );
	    }


	// ---------- what the two guidance fields become ----------

	    [Test]
	    public void NonDistilled_keeps_slider_in_cfg_scale(){
	        float cfg = 0;
	        float? distilled = 99;//deliberately dirty, Apply must clear it.

	        SD_DistilledGuidance.Apply( 7.5f, isDistilled:false, ref cfg, ref distilled );

	        Assert.AreEqual( 7.5f, cfg, 0.0001f );
	        Assert.IsNull( distilled, "a non-Flux request must not carry distilled_cfg_scale" );
	    }


	    [Test]
	    public void Distilled_moves_slider_across_and_pins_cfg_to_one(){
	        float cfg = 0;
	        float? distilled = null;

	        SD_DistilledGuidance.Apply( 3.5f, isDistilled:true, ref cfg, ref distilled );

	        Assert.AreEqual( 1f, cfg, 0.0001f, "cfg_scale must be 1, that is what disables the two-pass CFG" );
	        Assert.IsNotNull( distilled );
	        Assert.AreEqual( 3.5f, distilled.Value, 0.0001f );
	    }


	// ---------- the regression guard: unchanged JSON for everyone else ----------

	    [Test]
	    public void Txt2img_omits_the_field_entirely_when_not_distilled(){
	        var payload = new SD_txt2img_payload{
	            cfg_scale = 7f,
	            distilled_cfg_scale = null,
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };

	        string json = JsonConvert.SerializeObject( payload, SenderSettings() );

	        StringAssert.DoesNotContain( "distilled_cfg_scale", json,
	            "older webui builds never saw this field - a null must not be sent at all" );
	        StringAssert.Contains( "\"cfg_scale\": 7.0", json );
	    }


	    [Test]
	    public void Img2img_omits_the_field_entirely_when_not_distilled(){
	        var payload = new SD_img2img_payload{
	            cfg_scale = 7f,
	            distilled_cfg_scale = null,
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };

	        string json = JsonConvert.SerializeObject( payload, SenderSettings() );

	        StringAssert.DoesNotContain( "distilled_cfg_scale", json );
	    }


	    [Test]
	    public void Txt2img_sends_the_field_when_distilled(){
	        var payload = new SD_txt2img_payload{
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };
	        SD_DistilledGuidance.Apply( 3.5f, isDistilled:true,
	                                    ref payload.cfg_scale, ref payload.distilled_cfg_scale );

	        string json = JsonConvert.SerializeObject( payload, SenderSettings() );

	        StringAssert.Contains( "distilled_cfg_scale", json );
	        StringAssert.Contains( "\"cfg_scale\": 1.0", json );
	    }


	    [Test]
	    public void Img2img_sends_the_field_when_distilled(){
	        var payload = new SD_img2img_payload{
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };
	        SD_DistilledGuidance.Apply( 3.5f, isDistilled:true,
	                                    ref payload.cfg_scale, ref payload.distilled_cfg_scale );

	        string json = JsonConvert.SerializeObject( payload, SenderSettings() );

	        StringAssert.Contains( "distilled_cfg_scale", json );
	        StringAssert.Contains( "\"cfg_scale\": 1.0", json );
	    }


	// ---------- the field must survive the round trips the app puts payloads through ----------

	    [Test]
	    public void Clone_carries_the_field_over(){
	        var txt2img = new SD_txt2img_payload{
	            distilled_cfg_scale = 3.5f,
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };
	        var img2img = new SD_img2img_payload{
	            distilled_cfg_scale = 3.5f,
	            alwayson_scripts = new Dictionary<string, AlwaysOn_Value>(),
	        };

	        Assert.AreEqual( 3.5f, txt2img.Clone().distilled_cfg_scale.Value, 0.0001f );
	        Assert.AreEqual( 3.5f, img2img.Clone().distilled_cfg_scale.Value, 0.0001f );
	    }


	    // Project files store the payload, so an older save has no such field at all.
	    // It must come back as null rather than 0 - a 0 would be a real guidance value.
	    [Test]
	    public void Loading_an_older_save_leaves_the_field_null(){
	        string legacyJson = "{ \"cfg_scale\": 7.0, \"steps\": 20 }";

	        var txt2img = JsonConvert.DeserializeObject<SD_txt2img_payload>( legacyJson );
	        var img2img = JsonConvert.DeserializeObject<SD_img2img_payload>( legacyJson );

	        Assert.IsNull( txt2img.distilled_cfg_scale );
	        Assert.IsNull( img2img.distilled_cfg_scale );
	        Assert.AreEqual( 7f, txt2img.cfg_scale, 0.0001f );
	    }


	// ---------- must not explode while scenes are still loading ----------

	    [Test]
	    public void Reading_the_checkpoint_name_survives_missing_singletons(){
	        // In batchmode no scene is loaded, so both singletons are null. Generation
	        // code calls this every request, so it has to degrade quietly.
	        Assert.DoesNotThrow( () => SD_DistilledGuidance.currentCheckpoint_name() );
	        Assert.DoesNotThrow( () => SD_DistilledGuidance.isDistilled_active() );
	    }
	}
}//end namespace

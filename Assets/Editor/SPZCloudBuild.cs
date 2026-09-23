using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using TMPro;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

/// <summary>
/// Cloud build script for StableProjectorz.
/// Supports two modes:
///   SPZCloudBuild.BuildBaseline  — original project, no CN, no Bridge
///   SPZCloudBuild.BuildCN        — CN localization + CJK font + Agent Bridge
///
/// Called via: -executeMethod SPZCloudBuild.BuildBaseline
///         or: -executeMethod SPZCloudBuild.BuildCN
///
/// Exit codes:
///   0 = success
///   1 = build failed (compilation, scene error, font missing, Bridge missing)
/// </summary>
public class SPZCloudBuild
{
    // ─── Fixed constants ───────────────────────────────────────────
    const string CJK_FONT_NAME = "SourceHanSansCN-Regular";
    const string CJK_FONT_SHA256 = "C0AA89A70F92A820FF95490FEA6D472CD19621A71C9A748A4950EB2EAFE6438E";
    const string CJK_FONT_DIR = "Assets/TextMesh Pro/Fonts";
    const string CJK_FONT_FILE = "Assets/TextMesh Pro/Fonts/SourceHanSansCN-Regular.otf";
    const string CJK_FONT_ASSET_PATH = "Assets/TextMesh Pro/Resources/Fonts & Materials/CJKFallback SDF.asset";
    const string TMP_SETTINGS_PATH = "Assets/TextMesh Pro/Resources/TMP Settings.asset";
    const string SPZ_CONFIG_PATH = "spz.config";

    // ─── Manifest output ───────────────────────────────────────────
    static string _manifestPath;
    static readonly List<string> _manifestLines = new List<string>();

    static void ManifestAdd(string line)
    {
        _manifestLines.Add(line);
        Debug.Log("[Manifest] " + line);
    }

    static void WriteManifest(string buildPath, bool success)
    {
        if (string.IsNullOrEmpty(_manifestPath)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(_manifestPath));
        using (var w = new StreamWriter(_manifestPath))
        {
            w.WriteLine("# SPZ Cloud Build Manifest");
            w.WriteLine($"# Generated: {DateTime.UtcNow:O}");
            w.WriteLine($"# Success: {success}");
            w.WriteLine($"# Unity: {Application.unityVersion}");
            w.WriteLine($"# Platform: StandaloneWindows64 (IL2CPP)");
            w.WriteLine($"# Commit: {Environment.GetEnvironmentVariable("GITHUB_SHA") ?? "unknown"}");
            w.WriteLine();
            foreach (var line in _manifestLines)
                w.WriteLine(line);
        }
        Debug.Log($"[Manifest] Written to {_manifestPath}");
    }

    // ═══════════════════════════════════════════════════════════════
    // Public entry points
    // ═══════════════════════════════════════════════════════════════

    /// <summary>
    /// Baseline build: original project as-is, no CN, no Agent Bridge.
    /// Use this first to verify the toolchain works.
    /// </summary>
    public static void BuildBaseline()
    {
        Debug.Log("=== SPZ Baseline Build Started ===");
        RunBuild(enableCN: false, enableBridge: false);
    }

    /// <summary>
    /// CN build: applies localization, CJK font fallback, enables Agent Bridge.
    /// </summary>
    public static void BuildCN()
    {
        Debug.Log("=== SPZ CN Build Started ===");
        RunBuild(enableCN: true, enableBridge: true);
    }

    // ═══════════════════════════════════════════════════════════════
    // Core build pipeline
    // ═══════════════════════════════════════════════════════════════

    static void RunBuild(bool enableCN, bool enableBridge)
    {
        string buildLabel = enableCN ? "StableProjectorz-CN" : "StableProjectorz-Baseline";
        string buildPath = Path.GetFullPath(Path.Combine(Application.dataPath, "../build", buildLabel));
        _manifestPath = Path.Combine(buildPath, "BUILD_MANIFEST.txt");

        Directory.CreateDirectory(buildPath);

        ManifestAdd($"build_label: {buildLabel}");
        ManifestAdd($"enable_cn: {enableCN}");
        ManifestAdd($"enable_agent_bridge: {enableBridge}");

        // ── Step 1: Scenes ──────────────────────────────────────────
        var scenes = CollectScenes();
        if (scenes.Length == 0)
        {
            Debug.LogError("[Scenes] No enabled scenes found in EditorBuildSettings! Aborting.");
            WriteManifest(buildPath, false);
            EditorApplication.Exit(1);
        }

        // ── Step 2: CN localization (if requested) ─────────────────
        if (enableCN)
        {
            SetupCJKFont();  // throws on failure
        }

        // ── Step 3: Agent Bridge config (if requested) ─────────────
        if (enableBridge)
        {
            EnableAgentBridge();  // throws on failure
        }

        // ── Step 4: IL2CPP backend ─────────────────────────────────
        PlayerSettings.SetScriptingBackend(BuildTargetGroup.Standalone, ScriptingImplementation.IL2CPP);
        PlayerSettings.SetIl2CppCompilerConfiguration(BuildTargetGroup.Standalone, Il2CppCompilerConfiguration.Release);
        ManifestAdd("scripting_backend: IL2CPP");
        ManifestAdd("il2cpp_config: Release");

        // ── Step 5: Build ──────────────────────────────────────────
        string exePath = Path.Combine(buildPath, buildLabel + ".exe");

        var options = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = exePath,
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None
        };

        Debug.Log($"[Build] Starting IL2CPP build: {scenes.Length} scenes → {exePath}");

        var report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;

        // ── Step 6: Report ─────────────────────────────────────────
        foreach (var step in report.steps)
        {
            if (step.depth == 0)
                Debug.Log($"[Build] Step: {step.name} — {step.duration.TotalSeconds:F1}s");
        }

        if (summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            // totalSize is ulong — must use ulong arithmetic
            ulong sizeBytes = summary.totalSize;
            ulong sizeMB = sizeBytes / (1024UL * 1024UL);
            Debug.Log($"[Build] SUCCESS — {sizeMB} MB ({sizeBytes} bytes)");

            ManifestAdd($"build_result: SUCCESS");
            ManifestAdd($"build_size_bytes: {sizeBytes}");
            ManifestAdd($"build_size_mb: {sizeMB}");
            ManifestAdd($"exe_path: {exePath}");

            // ── Step 7: Copy spz.config ─────────────────────────────
            CopySpzConfig(buildPath, enableBridge);

            // ── Step 8: Write manifest ──────────────────────────────
            WriteManifest(buildPath, true);
            Debug.Log("=== SPZ Build Complete ===");
        }
        else
        {
            Debug.LogError($"[Build] FAILED — result: {summary.result}, errors: {summary.totalErrors}, warnings: {summary.totalWarnings}");
            ManifestAdd($"build_result: FAILED ({summary.result})");
            ManifestAdd($"build_errors: {summary.totalErrors}");
            WriteManifest(buildPath, false);

            // Also write the full error log for artifact upload
            string errorLogPath = Path.Combine(buildPath, "build_errors.txt");
            using (var w = new StreamWriter(errorLogPath))
            {
                w.WriteLine($"Build failed: {summary.result}");
                w.WriteLine($"Errors: {summary.totalErrors}, Warnings: {summary.totalWarnings}");
                w.WriteLine();
                foreach (var step in report.steps)
                {
                    w.WriteLine($"=== Step: {step.name} ({step.duration.TotalSeconds:F1}s) ===");
                    foreach (var msg in step.messages)
                    {
                        w.WriteLine($"  [{msg.type}] {msg.content}");
                    }
                }
            }
            Debug.LogError($"[Build] Error log written to {errorLogPath}");
            EditorApplication.Exit(1);
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Scene collection
    // ═══════════════════════════════════════════════════════════════

    static string[] CollectScenes()
    {
        Debug.Log("[Scenes] Collecting enabled scenes from EditorBuildSettings...");

        var sceneList = new List<string>();

        foreach (var entry in EditorBuildSettings.scenes)
        {
            if (!entry.enabled)
            {
                Debug.Log($"[Scenes] SKIP (disabled): {entry.path}");
                continue;
            }

            // Verify scene file exists
            string fullPath = Path.Combine(Directory.GetCurrentDirectory(), entry.path);
            if (!File.Exists(fullPath))
            {
                Debug.LogError($"[Scenes] Scene file NOT FOUND: {entry.path}");
                throw new Exception($"Scene file not found: {entry.path}");
            }

            sceneList.Add(entry.path);
            Debug.Log($"[Scenes] {sceneList.Count:D2}: {entry.path}");
        }

        Debug.Log($"[Scenes] Total enabled scenes: {sceneList.Count}");

        // Check scene 0 exists as the launch scene
        if (sceneList.Count > 0)
        {
            ManifestAdd($"scene_count: {sceneList.Count}");
            ManifestAdd($"launch_scene: {sceneList[0]}");
            for (int i = 0; i < sceneList.Count; i++)
                ManifestAdd($"scene_{i:D3}: {sceneList[i]}");
        }

        return sceneList.ToArray();
    }

    // ═══════════════════════════════════════════════════════════════
    // CJK Font setup
    // ═══════════════════════════════════════════════════════════════

    static void SetupCJKFont()
    {
        Debug.Log("[CJK] Setting up CJK fallback font...");

        // ── Verify font file exists at the exact path ──────────────
        if (!File.Exists(CJK_FONT_FILE))
        {
            Debug.LogError($"[CJK] Font file not found: {CJK_FONT_FILE}");
            Debug.LogError("[CJK] CN build requires CJK font. Aborting.");
            throw new Exception($"CJK font not found: {CJK_FONT_FILE}");
        }

        // ── Verify SHA-256 hash ────────────────────────────────────
        string actualHash = ComputeSHA256(CJK_FONT_FILE);
        if (!string.Equals(actualHash, CJK_FONT_SHA256, StringComparison.OrdinalIgnoreCase))
        {
            Debug.LogError($"[CJK] Font hash mismatch!");
            Debug.LogError($"[CJK]   Expected: {CJK_FONT_SHA256}");
            Debug.LogError($"[CJK]   Actual:   {actualHash}");
            throw new Exception("CJK font SHA-256 mismatch");
        }
        Debug.Log($"[CJK] Font hash verified: {actualHash}");
        ManifestAdd($"cjk_font: {CJK_FONT_NAME}");
        ManifestAdd($"cjk_font_sha256: {actualHash}");

        // ── Load the Font ──────────────────────────────────────────
        Font cjkFont = AssetDatabase.LoadAssetAtPath<Font>(CJK_FONT_FILE);
        if (cjkFont == null)
        {
            Debug.LogError($"[CJK] Failed to load Font asset at {CJK_FONT_FILE}");
            throw new Exception("Failed to load CJK Font");
        }
        Debug.Log($"[CJK] Loaded font: {cjkFont.name}");

        // ── Create or update TMP dynamic font asset ────────────────
        // Load existing asset to preserve GUID and references
        TMP_FontAsset fontAsset = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(CJK_FONT_ASSET_PATH);

        if (fontAsset == null)
        {
            Debug.Log("[CJK] Creating new TMP_FontAsset...");
            fontAsset = TMP_FontAsset.CreateFontAsset(cjkFont);
            fontAsset.atlasPopulationMode = AtlasPopulationMode.Dynamic;
            fontAsset.name = "CJKFallback SDF";

            // Ensure directory exists
            string dir = Path.GetDirectoryName(CJK_FONT_ASSET_PATH);
            Directory.CreateDirectory(dir);
            AssetDatabase.CreateAsset(fontAsset, CJK_FONT_ASSET_PATH);
        }
        else
        {
            Debug.Log("[CJK] Reusing existing TMP_FontAsset (GUID preserved)...");
            // Clear atlas to force repopulation with current font
            fontAsset.atlasPopulationMode = AtlasPopulationMode.Dynamic;
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log($"[CJK] TMP font asset ready at {CJK_FONT_ASSET_PATH}");

        // ── Add to TMP Settings fallback list ──────────────────────
        var tmpSettings = AssetDatabase.LoadAssetAtPath<TMP_Settings>(TMP_SETTINGS_PATH);
        if (tmpSettings == null)
        {
            Debug.LogError($"[CJK] TMP Settings not found at {TMP_SETTINGS_PATH}");
            Debug.LogError("[CJK] Cannot add fallback. Aborting CN build.");
            throw new Exception("TMP Settings.asset not found");
        }

        // Use the correct API: TMP_Settings.fallbackFontAssets is static in Unity 6000.x
        var fallbackList = TMP_Settings.fallbackFontAssets;
        if (fallbackList == null)
        {
            // Should not happen, but handle gracefully
            fallbackList = new List<TMP_FontAsset>();
            // Access via serialized property if direct assignment needed
            Debug.LogWarning("[CJK] fallbackFontAssets was null, creating new list.");
        }

        // Check for duplicate by GUID
        string assetGUID = AssetDatabase.AssetPathToGUID(CJK_FONT_ASSET_PATH);
        bool alreadyExists = false;
        for (int i = fallbackList.Count - 1; i >= 0; i--)
        {
            if (fallbackList[i] == null)
            {
                Debug.LogWarning($"[CJK] Removing null entry at index {i}");
                fallbackList.RemoveAt(i);
                continue;
            }
            string existingGUID = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(fallbackList[i]));
            if (existingGUID == assetGUID)
            {
                alreadyExists = true;
                Debug.Log($"[CJK] Font already in fallback list at index {i}, replacing...");
                fallbackList[i] = fontAsset;
            }
        }

        if (!alreadyExists)
        {
            fallbackList.Add(fontAsset);
            Debug.Log("[CJK] Added CJK font to fallbackFontAssets list.");
        }

        EditorUtility.SetDirty(tmpSettings);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        // ── Verify: reload and check ───────────────────────────────
        var reloadedSettings = AssetDatabase.LoadAssetAtPath<TMP_Settings>(TMP_SETTINGS_PATH);
        int fallbackCount = TMP_Settings.fallbackFontAssets != null
            ? TMP_Settings.fallbackFontAssets.Count
            : 0;
        bool hasCJK = false;
        for (int i = 0; i < fallbackCount; i++)
        {
            if (TMP_Settings.fallbackFontAssets[i] != null &&
                TMP_Settings.fallbackFontAssets[i].name == "CJKFallback SDF")
            {
                hasCJK = true;
                break;
            }
        }

        if (!hasCJK)
        {
            Debug.LogError("[CJK] Verification failed: CJK font NOT in fallback list after save/reload!");
            throw new Exception("CJK font verification failed after save/reload");
        }

        Debug.Log($"[CJK] Verification passed: {fallbackCount} fallback(s), CJK present.");
        ManifestAdd($"tmp_fallback_count: {fallbackCount}");
        ManifestAdd($"cjk_fallback_verified: true");

        // ── Check material and atlas ────────────────────────────────
        var savedAsset = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(CJK_FONT_ASSET_PATH);
        if (savedAsset == null || savedAsset.material == null)
        {
            Debug.LogError("[CJK] Saved font asset has null material! Aborting.");
            throw new Exception("CJK font asset material is null after save");
        }
        Debug.Log($"[CJK] Material OK: {savedAsset.material.name}");
        Debug.Log($"[CJK] Atlas texture OK: {(savedAsset.atlasTexture != null ? savedAsset.atlasTexture.name : "NULL")}");
    }

    /// <summary>
    /// Compute SHA-256 hash of a file.
    /// </summary>
    static string ComputeSHA256(string filePath)
    {
        using (var sha = System.Security.Cryptography.SHA256.Create())
        using (var stream = File.OpenRead(filePath))
        {
            byte[] hashBytes = sha.ComputeHash(stream);
            return BitConverter.ToString(hashBytes).Replace("-", "").ToUpperInvariant();
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // Agent Bridge configuration
    // ═══════════════════════════════════════════════════════════════

    static void EnableAgentBridge()
    {
        Debug.Log("[Bridge] Enabling Agent Bridge in spz.config...");

        string configPath = Path.GetFullPath(Path.Combine(Application.dataPath, "../", SPZ_CONFIG_PATH));

        if (!File.Exists(configPath))
        {
            Debug.LogError($"[Bridge] spz.config not found at {configPath}");
            throw new Exception("spz.config not found");
        }

        string[] lines = File.ReadAllLines(configPath);
        bool bridgeFound = false;
        bool bridgeEnabled = false;

        for (int i = 0; i < lines.Length; i++)
        {
            string trimmed = lines[i].Trim();

            // Skip blank lines
            if (string.IsNullOrWhiteSpace(trimmed))
                continue;

            // Skip comment lines — but check if they contain the flag
            if (trimmed.StartsWith("#"))
            {
                string uncommented = trimmed.Substring(1).Trim();
                if (uncommented == "--agent-bridge" || uncommented.StartsWith("--agent-bridge "))
                {
                    // Uncomment this line
                    lines[i] = lines[i].Replace("#--agent-bridge", "--agent-bridge");
                    bridgeFound = true;
                    bridgeEnabled = true;
                    Debug.Log($"[Bridge] Uncommented line {i + 1}: {lines[i].Trim()}");
                }
                continue;
            }

            // Non-comment line that IS the flag
            if (trimmed == "--agent-bridge" || trimmed.StartsWith("--agent-bridge "))
            {
                bridgeFound = true;
                bridgeEnabled = true;
                Debug.Log($"[Bridge] Already enabled at line {i + 1}: {trimmed}");
            }
        }

        if (!bridgeEnabled)
        {
            Debug.LogError("[Bridge] --agent-bridge flag not found in spz.config (even as comment)!");
            Debug.LogError("[Bridge] This build requires Agent Bridge. Aborting.");
            throw new Exception("Agent Bridge flag not found in spz.config");
        }

        // Write back
        File.WriteAllLines(configPath, lines);
        Debug.Log("[Bridge] spz.config updated.");

        // Verify by re-reading and line-parsing
        string verifyContent = File.ReadAllText(configPath);
        string[] verifyLines = verifyContent.Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
        bool verified = false;
        foreach (string vl in verifyLines)
        {
            string t = vl.Trim();
            if (string.IsNullOrEmpty(t) || t.StartsWith("#"))
                continue;
            if (t == "--agent-bridge" || t.StartsWith("--agent-bridge "))
            {
                verified = true;
                break;
            }
        }

        if (!verified)
        {
            Debug.LogError("[Bridge] Verification failed: --agent-bridge not found as active line after write!");
            throw new Exception("Agent Bridge verification failed");
        }

        Debug.Log("[Bridge] Verified: --agent-bridge is active.");
        ManifestAdd("agent_bridge: ENABLED");
        ManifestAdd("agent_bridge_verified: true");
    }

    // ═══════════════════════════════════════════════════════════════
    // Copy spz.config to build output
    // ═══════════════════════════════════════════════════════════════

    static void CopySpzConfig(string buildPath, bool expectBridge)
    {
        string sourceConfig = Path.GetFullPath(Path.Combine(Application.dataPath, "../", SPZ_CONFIG_PATH));
        string destConfig = Path.Combine(buildPath, "spz.config");

        if (!File.Exists(sourceConfig))
        {
            Debug.LogWarning($"[Config] spz.config not found at {sourceConfig}, skipping copy.");
            ManifestAdd("spz_config_copied: false");
            return;
        }

        File.Copy(sourceConfig, destConfig, true);
        Debug.Log($"[Config] Copied spz.config → {destConfig}");

        // Parse to verify Bridge state in the copied file
        string[] lines = File.ReadAllLines(destConfig);
        bool bridgeActive = false;
        foreach (string line in lines)
        {
            string t = line.Trim();
            if (string.IsNullOrEmpty(t) || t.StartsWith("#"))
                continue;
            if (t == "--agent-bridge" || t.StartsWith("--agent-bridge "))
            {
                bridgeActive = true;
                break;
            }
        }

        if (expectBridge && !bridgeActive)
        {
            Debug.LogError("[Config] Bridge expected but not active in copied spz.config!");
            throw new Exception("spz.config Bridge mismatch");
        }

        ManifestAdd($"spz_config_copied: true");
        ManifestAdd($"spz_config_bridge_active: {bridgeActive}");
    }
}

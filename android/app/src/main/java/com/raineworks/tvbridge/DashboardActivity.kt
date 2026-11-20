package com.raineworks.tvbridge

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject

/**
 * A Home Assistant dashboard, full screen. It signs in as Home Assistant's
 * phone apps do ("external auth"): the frontend asks this app for its access
 * token, which the integration made for this TV's own user and sent with the
 * dashboard. The sidebar is hidden; Back goes back, then closes it.
 */
class DashboardActivity : Activity() {

    private lateinit var web: WebView
    // Read from the frontend's thread (JavaScript calls)
    @Volatile private var token: String = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        web = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = WebViewClient()
            addJavascriptInterface(Bridge(), "externalApp")
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            // The sidebar hidden (the frontend's own setting), before it reads it
            WebViewCompat.addDocumentStartJavaScript(
                web,
                "try{localStorage.setItem('dockedSidebar','\"always_hidden\"')}catch(e){}",
                setOf("*"),
            )
        }
        setContentView(web)
        current = this
        load(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        load(intent)
    }

    override fun onDestroy() {
        if (current === this) current = null
        web.destroy()
        super.onDestroy()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun load(intent: Intent) {
        val url = intent.getStringExtra(EXTRA_URL)
        val access = tokens.remove(intent.getStringExtra(EXTRA_TOKEN))
        if (url == null || access == null) {
            finish()
            return
        }
        token = access
        val separator = if ('?' in url) '&' else '?'
        web.loadUrl("$url${separator}external_auth=1")
    }

    private fun js(script: String) {
        runOnUiThread { web.evaluateJavascript(script, null) }
    }

    /** What the frontend calls as window.externalApp. */
    private inner class Bridge {
        @JavascriptInterface
        fun getExternalAuth(payload: String) {
            val callback = JSONObject(payload).optString("callback")
            if (!CALLBACK.matches(callback)) return
            val auth = JSONObject().put("access_token", token).put("expires_in", TOKEN_SECONDS)
            js("window.$callback(true, $auth);")
        }

        @JavascriptInterface
        fun revokeExternalAuth(payload: String) {
            val callback = JSONObject(payload).optString("callback")
            if (CALLBACK.matches(callback)) js("window.$callback(true);")
            runOnUiThread { finish() }
        }

        /** The frontend's messages: it waits for its config; the rest needs no answer. */
        @JavascriptInterface
        fun externalBus(message: String) {
            val json = try {
                JSONObject(message)
            } catch (e: org.json.JSONException) {
                Log.w(TAG, "Odd message from the dashboard: $e")
                return
            }
            if (json.optString("type") != "config/get") return
            val config = JSONObject()
                .put("hasSettingsScreen", false)
                .put("canWriteTag", false)
                .put("hasExoPlayer", false)
                .put("canCommissionMatter", false)
                .put("canImportThreadCredentials", false)
                .put("hasAssist", false)
                .put("hasBarCodeScanner", 0)
            val reply = JSONObject()
                .put("id", json.opt("id"))
                .put("type", "result")
                .put("success", true)
                .put("result", config)
            js("window.externalBus($reply);")
        }
    }

    companion object {
        private const val TAG = "TvBridge"
        private const val EXTRA_URL = "url"
        private const val EXTRA_TOKEN = "token"
        // The integration's tokens last for years: the frontend needn't ask often
        private const val TOKEN_SECONDS = 86_400
        private val CALLBACK = Regex("^[A-Za-z_$][A-Za-z0-9_$]*$")

        // Access tokens by id, so they're never in an Intent
        private val tokens = java.util.concurrent.ConcurrentHashMap<String, String>()

        @Volatile
        private var current: DashboardActivity? = null

        fun start(context: Context, url: String, token: String) {
            val id = java.util.UUID.randomUUID().toString()
            tokens[id] = token
            context.startActivity(
                Intent(context, DashboardActivity::class.java)
                    .putExtra(EXTRA_URL, url)
                    .putExtra(EXTRA_TOKEN, id)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
        }

        fun stop() {
            current?.let { activity -> activity.runOnUiThread { activity.finish() } }
        }
    }
}

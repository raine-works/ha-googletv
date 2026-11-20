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
import android.net.Uri
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
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
 *
 * It stays on Home Assistant: a link elsewhere isn't followed, and the
 * token is given only to a page from Home Assistant's own address.
 */
class DashboardActivity : Activity() {

    private lateinit var web: WebView
    // Read from the frontend's thread (JavaScript calls)
    @Volatile private var token: String = ""
    // Home Assistant's address (scheme, host, port): the only one it shows
    @Volatile private var origin: String = ""
    // The page's address, kept on the main thread for the JavaScript calls
    @Volatile private var pageUrl: String = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        web = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                    originOf(request.url.toString()) != origin

                override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                    pageUrl = url
                }

                override fun onReceivedError(
                    view: WebView,
                    request: WebResourceRequest,
                    error: android.webkit.WebResourceError,
                ) {
                    if (request.isForMainFrame) failed(error.description.toString())
                }

                override fun onReceivedSslError(
                    view: WebView,
                    handler: android.webkit.SslErrorHandler,
                    error: android.net.http.SslError,
                ) {
                    // Not trusted (a self-signed certificate): said, not shown blank
                    handler.cancel()
                    failed(getString(R.string.dashboard_certificate))
                }
            }
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

    override fun onStop() {
        super.onStop()
        // Left for another app or the home screen: closed, signed out
        finish()
    }

    override fun onDestroy() {
        if (current === this) current = null
        Events.emit("dashboard", JSONObject().put("state", "closed"))
        (web.parent as? android.view.ViewGroup)?.removeView(web)
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
        Events.emit("dashboard", JSONObject().put("state", "opened").put("url", url))
        origin = originOf(url)
        pageUrl = url
        val separator = if ('?' in url) '&' else '?'
        web.loadUrl("$url${separator}external_auth=1")
    }

    /** Why the dashboard couldn't open, in place of a blank page. */
    private fun failed(reason: String) {
        Log.w(TAG, "Couldn't open the dashboard: $reason")
        val box = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setBackgroundColor(Theme.BACKGROUND)
            setPadding(Theme.dp(this@DashboardActivity, 96), 0, Theme.dp(this@DashboardActivity, 96), 0)
        }
        fun line(text: String, sp: Float, color: Int, face: android.graphics.Typeface) =
            android.widget.TextView(this).apply {
                this.text = text
                setTextColor(color)
                textSize = sp
                typeface = face
                gravity = android.view.Gravity.CENTER
                setPadding(0, Theme.dp(this@DashboardActivity, 6), 0, Theme.dp(this@DashboardActivity, 6))
            }
        box.addView(line(getString(R.string.dashboard_failed), 26f, Theme.FOREGROUND, Theme.semibold(this)))
        box.addView(line(reason, 16f, Theme.MUTED_FOREGROUND, Theme.regular(this)))
        token = ""
        setContentView(box)
    }

    /** Only for a page on Home Assistant's own address. */
    private fun trusted(): Boolean = origin.isNotEmpty() && originOf(pageUrl) == origin

    private fun js(script: String) {
        runOnUiThread { web.evaluateJavascript(script, null) }
    }

    /** What the frontend calls as window.externalApp. */
    private inner class Bridge {
        @JavascriptInterface
        fun getExternalAuth(payload: String) {
            val callback = callbackOf(payload) ?: return
            if (!trusted()) {
                Log.w(TAG, "A page off Home Assistant asked for its token: refused")
                js("window.$callback(false);")
                return
            }
            val auth = JSONObject().put("access_token", token).put("expires_in", TOKEN_SECONDS)
            js("window.$callback(true, $auth);")
        }

        @JavascriptInterface
        fun revokeExternalAuth(payload: String) {
            if (!trusted()) return
            callbackOf(payload)?.let { js("window.$it(true);") }
            runOnUiThread { finish() }
        }

        /** The frontend's messages: it waits for its config; the rest needs no answer. */
        @JavascriptInterface
        fun externalBus(message: String) {
            if (!trusted()) return
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

    /** The JavaScript callback a payload names, if it's a plain name and the payload is JSON. */
    private fun callbackOf(payload: String): String? = try {
        JSONObject(payload).optString("callback").takeIf { CALLBACK.matches(it) }
    } catch (e: org.json.JSONException) {
        null
    }

    companion object {
        private const val TAG = "TvBridge"
        private const val EXTRA_URL = "url"

        /** scheme://host:port, the parts that make an address the same site. */
        fun originOf(url: String): String {
            val uri = Uri.parse(url)
            val scheme = uri.scheme?.lowercase() ?: return ""
            val port = if (uri.port != -1) uri.port else if (scheme == "https") 443 else 80
            return "$scheme://${uri.host?.lowercase()}:$port"
        }
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

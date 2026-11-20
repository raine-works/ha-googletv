package com.raineworks.tvbridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.TypedValue
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * The app's one screen: whether it's running and paired, its permissions,
 * the "don't pop up over" rules, and a test notification. Built in code with
 * the platform's own widgets, so the remote's D-pad moves through it as is.
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var content: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        BridgeService.start(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(64), dp(40), dp(64), dp(40))
        }
        setContentView(ScrollView(this).apply { addView(content) })
    }

    override fun onResume() {
        super.onResume()
        build()
    }

    private fun build() {
        content.removeAllViews()
        heading(getString(R.string.app_name), 32f)
        section(getString(R.string.status_title))
        line(getString(R.string.status_running, ipAddress() ?: "?", ApiServer.PORT))
        val paired = prefs.tokens.size
        line(
            if (paired > 0) getString(R.string.status_paired, paired)
            else getString(R.string.status_not_paired),
        )
        permission(
            TvInfo.overlayAllowed(this),
            R.string.permission_overlay_ok,
            R.string.permission_overlay_missing,
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
        )
        permission(
            TvInfo.usageAccess(this),
            R.string.permission_usage_ok,
            R.string.permission_usage_missing,
            Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS),
        )
        button(getString(R.string.test_button)) {
            Notifier.handle(
                this,
                NotificationRequest(
                    title = getString(R.string.test_title),
                    message = getString(R.string.test_message),
                    imageUrl = null, videoUrl = null,
                    mode = NotificationRequest.MODE_POPUP, position = "top_right",
                    durationS = 8, size = "medium", color = null, mute = true,
                    ignoreRules = true, whenBlocked = null, tag = "test",
                    contextApp = null, contextInput = null,
                ),
            )
        }

        section(getString(R.string.rules_title))
        line(getString(R.string.rules_help))
        sub(getString(R.string.rules_inputs))
        val inputs = TvInfo.inputs(this)
        if (inputs.isEmpty()) line(getString(R.string.no_inputs))
        inputs.forEach { input ->
            check(input.name, input.id in prefs.blockedInputs) { on ->
                prefs.blockedInputs = if (on) prefs.blockedInputs + input.id else prefs.blockedInputs - input.id
            }
        }
        sub(getString(R.string.rules_apps))
        TvInfo.apps(this).filter { it.packageName != packageName }.forEach { app ->
            check(app.name, app.packageName in prefs.blockedApps) { on ->
                prefs.blockedApps = if (on) prefs.blockedApps + app.packageName else prefs.blockedApps - app.packageName
            }
        }

        section("")
        button(getString(R.string.forget_button)) {
            prefs.forgetAll()
            Toast.makeText(this, R.string.forgotten, Toast.LENGTH_SHORT).show()
            build()
        }
    }

    private fun permission(allowed: Boolean, ok: Int, missing: Int, settings: Intent) {
        if (allowed) {
            line(getString(ok))
            return
        }
        button(getString(missing)) {
            if (settings.resolveActivity(packageManager) != null) {
                startActivity(settings)
            } else {
                Toast.makeText(this, R.string.permission_unavailable, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun heading(text: String, sp: Float) {
        content.addView(label(text, sp, bold = true, color = Color.WHITE))
    }

    private fun section(text: String) {
        content.addView(
            label(text, 22f, bold = true, color = Color.rgb(66, 165, 245)).apply {
                setPadding(0, dp(28), 0, dp(8))
            },
        )
    }

    private fun sub(text: String) {
        content.addView(label(text, 18f, bold = true, color = Color.WHITE).apply { setPadding(0, dp(16), 0, dp(4)) })
    }

    private fun line(text: String) {
        content.addView(label(text, 16f, bold = false, color = Color.rgb(200, 208, 222)))
    }

    private fun button(text: String, onClick: () -> Unit) {
        content.addView(
            Button(this).apply {
                this.text = text
                isAllCaps = false
                setOnClickListener { onClick() }
            },
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(8) },
        )
    }

    private fun check(text: String, checked: Boolean, onChange: (Boolean) -> Unit) {
        content.addView(
            CheckBox(this).apply {
                this.text = text
                isChecked = checked
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
                setOnCheckedChangeListener { _, on -> onChange(on) }
            },
        )
    }

    private fun label(text: String, sp: Float, bold: Boolean, color: Int): TextView =
        TextView(this).apply {
            this.text = text
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            if (bold) typeface = Typeface.DEFAULT_BOLD
            visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        }

    private fun dp(value: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), resources.displayMetrics,
    ).toInt()

    /** The TV's address on the network, for the status line. */
    private fun ipAddress(): String? = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { it is Inet4Address }?.hostAddress
    } catch (e: java.net.SocketException) {
        null
    }
}

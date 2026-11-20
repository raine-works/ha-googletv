package com.raineworks.tvbridge

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * The app's one screen, in the Home Assistant dashboards' look: whether it's
 * connected, its permissions, pop-ups' size and place, the "don't pop up
 * over" rules. Built in code; the remote's D-pad moves through it, a ring
 * marking where it is.
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var content: LinearLayout
    private lateinit var scroll: ScrollView
    private val main = Handler(Looper.getMainLooper())
    // Network debugging, while setting up: null until checked
    private var debugging: Boolean? = null
    private var resumed = false

    /** While it's not paired: watch for debugging and pairing, and move on as they happen. */
    private val watch = object : Runnable {
        override fun run() {
            if (!resumed) return
            val wasPaired = prefs.tokens.isNotEmpty()
            Thread {
                val on = TvInfo.networkDebugging()
                main.post {
                    if (!resumed) return@post
                    val paired = prefs.tokens.isNotEmpty()
                    if (on != debugging || paired != wasPaired) {
                        debugging = on
                        build()
                    }
                    if (!paired) main.postDelayed(this, WATCH_MS)
                }
            }.start()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        BridgeService.start(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        window.decorView.setBackgroundColor(Theme.BACKGROUND)
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(56), dp(40), dp(56), dp(48))
        }
        scroll = ScrollView(this).apply {
            isFillViewport = true
            addView(
                FrameLayout(this@MainActivity).apply {
                    addView(content, FrameLayout.LayoutParams(dp(880), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_HORIZONTAL))
                },
            )
        }
        setContentView(scroll)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        build()
        if (prefs.tokens.isEmpty()) main.post(watch)
    }

    override fun onPause() {
        super.onPause()
        resumed = false
        main.removeCallbacks(watch)
    }

    private fun build() {
        // Where the remote was, by its place among the focusable controls
        val focusedIndex = content.getFocusables(View.FOCUS_DOWN).indexOf(currentFocus)
        content.removeAllViews()
        header()

        val paired = prefs.tokens.size
        if (paired == 0) setupCard()
        card(getString(R.string.status_title)) {
            row(it, getString(R.string.status_address), "${ipAddress() ?: "?"}:${ApiServer.PORT}")
            row(
                it,
                getString(R.string.status_home_assistant),
                if (paired > 0) getString(R.string.status_paired, paired) else getString(R.string.status_not_paired),
            )
        }

        card(getString(R.string.permissions_title)) {
            permissionRow(
                it,
                getString(R.string.permission_overlay),
                TvInfo.overlayAllowed(this),
                Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
            )
            permissionRow(
                it,
                getString(R.string.permission_usage),
                TvInfo.usageAccess(this),
                Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS),
            )
        }

        card(getString(R.string.popups_title), getString(R.string.popups_subtitle)) {
            label(it, getString(R.string.default_size))
            chips(
                it,
                NotificationRequest.SIZES.map { size -> size to getString(sizeName(size)) },
                prefs.defaultSize,
            ) { size -> prefs.defaultSize = size }
            label(it, getString(R.string.default_position))
            val positions = listOf(
                "top_left", "top", "top_right", "center", "bottom_left", "bottom", "bottom_right",
            ).map { position -> position to getString(positionName(position)) }
            chips(it, positions.take(4), prefs.defaultPosition) { position -> prefs.defaultPosition = position }
            chips(it, positions.drop(4), prefs.defaultPosition) { position -> prefs.defaultPosition = position }
            button(it, getString(R.string.test_button), primary = true) {
                Notifier.handle(
                    this,
                    NotificationRequest(
                        title = getString(R.string.test_title),
                        message = getString(R.string.test_message),
                        imageUrl = null, videoUrl = null,
                        mode = NotificationRequest.MODE_POPUP,
                        position = prefs.defaultPosition, durationS = 8, size = prefs.defaultSize,
                        color = null, mute = true, ignoreRules = true, whenBlocked = null,
                        tag = "test", contextApp = null, contextInput = null,
                    ),
                )
            }
            // Live ones stay until Home Assistant takes them down: or this
            button(it, getString(R.string.clear_button)) {
                Notifier.dismiss(this, null)
                Toast.makeText(this, R.string.cleared, Toast.LENGTH_SHORT).show()
            }
        }

        card(getString(R.string.rules_title), getString(R.string.rules_subtitle)) {
            label(it, getString(R.string.rules_inputs))
            val inputs = TvInfo.inputs(this)
            if (inputs.isEmpty()) muted(it, getString(R.string.no_inputs))
            inputs.forEach { input ->
                toggleRow(it, input.name, input.id in prefs.blockedInputs) { on ->
                    prefs.blockedInputs = if (on) prefs.blockedInputs + input.id else prefs.blockedInputs - input.id
                }
            }
            label(it, getString(R.string.rules_apps))
            TvInfo.apps(this).filter { app -> app.packageName != packageName }.forEach { app ->
                toggleRow(it, app.name, app.packageName in prefs.blockedApps) { on ->
                    prefs.blockedApps = if (on) prefs.blockedApps + app.packageName else prefs.blockedApps - app.packageName
                }
            }
            label(it, getString(R.string.when_blocked))
            chips(
                it,
                listOf(
                    Prefs.WHEN_BLOCKED_PANEL to getString(R.string.when_blocked_panel),
                    Prefs.WHEN_BLOCKED_DROP to getString(R.string.when_blocked_drop),
                ),
                prefs.whenBlocked,
            ) { value -> prefs.whenBlocked = value }
        }

        card(getString(R.string.pairing_section)) {
            button(it, getString(R.string.forget_button), destructive = true) {
                prefs.forgetAll()
                Toast.makeText(this, R.string.forgotten, Toast.LENGTH_SHORT).show()
                build()
            }
        }

        // Keep the remote's place after a rebuild
        if (focusedIndex >= 0) {
            content.getFocusables(View.FOCUS_DOWN).getOrNull(focusedIndex)?.requestFocus()
        }
    }

    /**
     * Setting up, while Home Assistant isn't paired: a QR code to the
     * integration in HACS, network debugging (with a way to its settings),
     * then adding the TV in Home Assistant, which pairs by itself.
     */
    private fun setupCard() {
        card(getString(R.string.setup_title), getString(R.string.setup_subtitle)) { body ->
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.TOP
                setPadding(0, dp(8), 0, 0)
                clipChildren = false
                clipToPadding = false
            }
            row.addView(
                ImageView(this).apply {
                    setImageBitmap(Qr.bitmap(Qr.HACS_URL, dp(176)))
                    background = Theme.surface(this@MainActivity, Color.WHITE, 12, Color.WHITE)
                    setPadding(dp(12), dp(12), dp(12), dp(12))
                    contentDescription = getString(R.string.setup_qr)
                },
                LinearLayout.LayoutParams(dp(200), dp(200)),
            )
            val steps = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(28), 0, 0, 0)
                clipChildren = false
                clipToPadding = false
            }
            step(steps, 1, getString(R.string.setup_hacs_title), getString(R.string.setup_hacs_text))
            val developer = TvInfo.developerOptions(this)
            val on = debugging
            step(
                steps,
                2,
                getString(R.string.setup_debugging_title),
                getString(
                    when {
                        on == true -> R.string.setup_debugging_done
                        developer -> R.string.setup_debugging_text
                        else -> R.string.setup_developer_text
                    },
                ),
                when (on) {
                    null -> null
                    true -> getString(R.string.setup_on) to Theme.SUCCESS
                    false -> getString(R.string.setup_off) to Theme.WARNING
                },
            )
            if (on == false) {
                button(steps, getString(R.string.setup_open_settings), primary = true) {
                    val settings = Intent(
                        if (developer) Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS else Settings.ACTION_DEVICE_INFO_SETTINGS,
                    )
                    if (settings.resolveActivity(packageManager) != null) {
                        startActivity(settings)
                    } else {
                        Toast.makeText(this, R.string.permission_unavailable, Toast.LENGTH_LONG).show()
                    }
                }
            }
            step(steps, 3, getString(R.string.setup_add_title), getString(R.string.setup_add_text))
            row.addView(steps, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            body.addView(row)
        }
    }

    /** A numbered step: its title (and a status pill), the text under it. */
    private fun step(parent: LinearLayout, number: Int, title: String, value: String, status: Pair<String, Int>? = null) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
            setPadding(0, if (parent.childCount == 0) 0 else dp(16), 0, 0)
        }
        row.addView(
            text(number.toString(), 13f, Theme.semibold(this), Theme.FOREGROUND).apply {
                gravity = Gravity.CENTER
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Theme.MUTED)
                }
            },
            LinearLayout.LayoutParams(dp(26), dp(26)),
        )
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(3), 0, 0)
        }
        val heading = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        heading.addView(text(title, 15f, Theme.semibold(this), Theme.FOREGROUND))
        status?.let { (word, color) ->
            heading.addView(
                pill(word, color),
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    marginStart = dp(10)
                },
            )
        }
        texts.addView(heading)
        texts.addView(
            text(value, 13f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                setPadding(0, dp(4), 0, 0)
                setLineSpacing(0f, 1.15f)
            },
        )
        row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        parent.addView(row)
    }

    // Pieces

    private fun header() {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(24))
        }
        row.addView(
            ImageView(this).apply { setImageResource(R.drawable.logo_gtv) },
            LinearLayout.LayoutParams(dp(52), dp(52)),
        )
        val titles = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), 0, 0, 0)
        }
        titles.addView(text(getString(R.string.header_title), 26f, Theme.semibold(this), Theme.FOREGROUND))
        titles.addView(text(getString(R.string.app_maker, BuildConfig.VERSION_NAME), 13f, Theme.regular(this), Theme.MUTED_FOREGROUND))
        row.addView(titles, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val paired = prefs.tokens.isNotEmpty()
        row.addView(
            pill(
                getString(if (paired) R.string.pill_paired else R.string.pill_not_paired),
                if (paired) Theme.SUCCESS else Theme.WARNING,
            ),
        )
        content.addView(row)
    }

    /** A card: a header (title, a line under it) over its rows. */
    private fun card(title: String, subtitle: String? = null, fill: (LinearLayout) -> Unit) {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Theme.surface(this@MainActivity, Theme.CARD, 12)
            setPadding(dp(24), dp(18), dp(24), dp(20))
            // Rows reach 12 dp into the padding, their focus ring with them
            clipChildren = false
            clipToPadding = false
        }
        card.addView(text(title, 17f, Theme.semibold(this), Theme.FOREGROUND))
        subtitle?.let {
            card.addView(text(it, 13f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply { setPadding(0, dp(2), 0, 0) })
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(10), 0, 0)
            clipChildren = false
            clipToPadding = false
        }
        fill(body)
        card.addView(body)
        content.addView(
            card,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(16)
            },
        )
    }

    private fun row(parent: LinearLayout, name: String, value: String) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(8), 0, dp(8))
        }
        row.addView(text(name, 14f, Theme.regular(this), Theme.MUTED_FOREGROUND), LinearLayout.LayoutParams(dp(200), ViewGroup.LayoutParams.WRAP_CONTENT))
        row.addView(text(value, 14f, Theme.medium(this), Theme.FOREGROUND), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        parent.addView(row)
    }

    private fun permissionRow(parent: LinearLayout, name: String, allowed: Boolean, settings: Intent) {
        val row = focusRow(parent, enabled = !allowed) {
            if (settings.resolveActivity(packageManager) != null) {
                startActivity(settings)
            } else {
                Toast.makeText(this, R.string.permission_unavailable, Toast.LENGTH_LONG).show()
            }
        }
        row.addView(text(name, 14f, Theme.medium(this), Theme.FOREGROUND), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(
            pill(
                getString(if (allowed) R.string.allowed else R.string.not_allowed),
                if (allowed) Theme.SUCCESS else Theme.WARNING,
            ),
        )
    }

    private fun toggleRow(parent: LinearLayout, name: String, on: Boolean, onChange: (Boolean) -> Unit) {
        val toggle = Toggle(this, on)
        val row = focusRow(parent) {
            toggle.on = !toggle.on
            onChange(toggle.on)
        }
        row.addView(text(name, 14f, Theme.medium(this), Theme.FOREGROUND), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(toggle, LinearLayout.LayoutParams(dp(40), dp(22)))
    }

    /** A row the remote can land on and select. */
    private fun focusRow(parent: LinearLayout, enabled: Boolean = true, onClick: () -> Unit): LinearLayout {
        val row = LinearLayout(this).apply {
            id = View.generateViewId()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
            if (enabled) {
                isFocusable = true
                isClickable = true
                background = Theme.focusable(this@MainActivity, Color.TRANSPARENT, 8, Color.TRANSPARENT)
                setOnClickListener { onClick() }
            }
        }
        parent.addView(
            row,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                setMargins(-dp(16), -dp(3), -dp(16), -dp(3))
            },
        )
        return row
    }

    /** A row of choices: the picked one filled. */
    private fun chips(
        parent: LinearLayout,
        options: List<Pair<String, String>>,
        selected: String,
        onPick: (String) -> Unit,
    ) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, 0)
            clipChildren = false
            clipToPadding = false
            // The chips' focus gap lines their edge up with the text above
            translationX = -dp(Theme.FOCUS_GAP_DP).toFloat()
        }
        options.forEach { (value, name) ->
            val picked = value == selected
            row.addView(
                text(name, 13f, Theme.medium(this), if (picked) Theme.PRIMARY_FOREGROUND else Theme.FOREGROUND).apply {
                    id = View.generateViewId()
                    gravity = Gravity.CENTER
                    isFocusable = true
                    isClickable = true
                    setPadding(dp(20), dp(13), dp(20), dp(13))
                    Theme.lift(this)
                    background = Theme.focusable(
                        this@MainActivity,
                        if (picked) Theme.PRIMARY else Color.TRANSPARENT,
                        999,
                        if (picked) Theme.PRIMARY else Theme.withAlpha(Color.WHITE, 40),
                    )
                    setOnClickListener {
                        onPick(value)
                        build()
                    }
                },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                    marginEnd = dp(2)
                },
            )
        }
        parent.addView(row)
    }

    private fun button(parent: LinearLayout, name: String, primary: Boolean = false, destructive: Boolean = false, onClick: () -> Unit) {
        val color = when {
            primary -> Theme.PRIMARY_FOREGROUND
            destructive -> Theme.DESTRUCTIVE
            else -> Theme.FOREGROUND
        }
        parent.addView(
            text(name, 14f, Theme.medium(this), color).apply {
                id = View.generateViewId()
                isFocusable = true
                isClickable = true
                setPadding(dp(22), dp(15), dp(22), dp(15))
                Theme.lift(this, 1.03f)
                background = Theme.focusable(
                    this@MainActivity,
                    if (primary) Theme.PRIMARY else Color.TRANSPARENT,
                    Theme.RADIUS_DP,
                    if (primary) Theme.PRIMARY else Theme.withAlpha(if (destructive) Theme.DESTRUCTIVE else Color.WHITE, 60),
                )
                setOnClickListener { onClick() }
            },
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(10)
                marginStart = -dp(Theme.FOCUS_GAP_DP)
            },
        )
    }

    private fun label(parent: LinearLayout, name: String) {
        parent.addView(
            text(name.uppercase(), 11f, Theme.semibold(this), Theme.MUTED_FOREGROUND).apply {
                letterSpacing = 0.08f
                setPadding(0, dp(12), 0, dp(4))
            },
        )
    }

    private fun muted(parent: LinearLayout, value: String) {
        parent.addView(text(value, 14f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply { setPadding(0, dp(4), 0, dp(4)) })
    }

    /** A status pill: a dot and a word, tinted. */
    private fun pill(value: String, color: Int): View =
        LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(5), dp(12), dp(5))
            background = GradientDrawable().apply {
                setColor(Theme.withAlpha(color, 36))
                cornerRadius = dp(999).toFloat()
                setStroke(dp(1), Theme.withAlpha(color, 90))
            }
            addView(
                View(this@MainActivity).apply {
                    background = GradientDrawable().apply {
                        shape = GradientDrawable.OVAL
                        setColor(color)
                    }
                },
                LinearLayout.LayoutParams(dp(7), dp(7)).apply { marginEnd = dp(7) },
            )
            addView(text(value, 12f, Theme.medium(this@MainActivity), Theme.FOREGROUND))
        }

    private fun text(value: String, sp: Float, typeface: Typeface, color: Int): TextView =
        TextView(this).apply {
            text = value
            setTextColor(color)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            this.typeface = typeface
            includeFontPadding = false
            ellipsize = TextUtils.TruncateAt.END
        }

    private fun sizeName(size: String): Int = when (size) {
        "compact" -> R.string.size_compact
        "medium" -> R.string.size_medium
        "large" -> R.string.size_large
        else -> R.string.size_small
    }

    private fun positionName(position: String): Int = when (position) {
        "top_left" -> R.string.position_top_left
        "top" -> R.string.position_top
        "center" -> R.string.position_center
        "bottom_left" -> R.string.position_bottom_left
        "bottom" -> R.string.position_bottom
        "bottom_right" -> R.string.position_bottom_right
        else -> R.string.position_top_right
    }

    private fun dp(value: Number): Int = Theme.dp(this, value)

    companion object {
        private const val WATCH_MS = 3000L
    }

    /** The TV's address on the network, for the status card. */
    private fun ipAddress(): String? = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { it is Inet4Address }?.hostAddress
    } catch (e: java.net.SocketException) {
        null
    }

    /** The dashboards' switch: a bar with the controls' radius, filled when on. */
    private class Toggle(context: Context, initial: Boolean) : View(context) {
        var on: Boolean = initial
            set(value) {
                field = value
                invalidate()
            }
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val rect = RectF()

        override fun onDraw(canvas: Canvas) {
            val radius = height * 0.3f
            rect.set(0f, 0f, width.toFloat(), height.toFloat())
            paint.color = if (on) Theme.PRIMARY else Theme.MUTED
            canvas.drawRoundRect(rect, radius, radius, paint)
            val inset = height * 0.14f
            val thumb = height - inset * 2
            val left = if (on) width - inset - thumb else inset
            rect.set(left, inset, left + thumb, inset + thumb)
            paint.color = if (on) Theme.PRIMARY_FOREGROUND else Theme.FOREGROUND
            canvas.drawRoundRect(rect, radius * 0.7f, radius * 0.7f, paint)
        }
    }
}

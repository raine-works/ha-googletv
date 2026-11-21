package com.raineworks.tvbridge

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
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
 * The app's one screen, in the Home Assistant dashboards' look, laid out
 * like the TV's own settings: the sections down the left (Home, Apps,
 * Pop-ups, Permissions, ADB, About), the one the remote is on to the right.
 * Built in code; the D-pad moves through it, a ring marking where it is.
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var nav: LinearLayout
    private lateinit var railStatus: LinearLayout
    private lateinit var content: LinearLayout
    private lateinit var scroll: ScrollView
    private val main = Handler(Looper.getMainLooper())
    // Network debugging, while setting up: null until checked
    private var debugging: Boolean? = null
    private var resumed = false

    private var section = Section.HOME
    private val navItems = mutableMapOf<Section, View>()
    // Apps' icons, loaded once
    private val appIcons = HashMap<String, Drawable?>()

    // What the screen shows that changes on its own: rebuilt when it does
    private var shown: String? = null
    // The pairing request last shown: a new one brings Home forward
    private var requestShown: String? = null
    // Building the content: focus the rail gets meanwhile isn't the remote's
    private var rebuilding = false

    private enum class Section(val icon: String, val title: Int, val subtitle: Int) {
        HOME("mdi:home-assistant", R.string.nav_home, R.string.home_subtitle),
        APPS("mdi:apps", R.string.nav_apps, R.string.apps_subtitle),
        POPUPS("mdi:bell-outline", R.string.nav_popups, R.string.popups_subtitle),
        PERMISSIONS("mdi:shield-check-outline", R.string.nav_permissions, R.string.permissions_subtitle),
        ADB("mdi:lan-connect", R.string.nav_adb, R.string.adb_subtitle),
        ABOUT("mdi:information-outline", R.string.nav_about, R.string.about_subtitle),
    }

    /**
     * While it's open: a request to connect, pairing, permissions given,
     * debugging turned on, rules changed from Home Assistant. The screen
     * moves on as they happen.
     */
    private val watch = object : Runnable {
        override fun run() {
            if (!resumed) return
            Thread {
                val on = TvInfo.networkDebugging()
                main.post {
                    if (!resumed) return@post
                    debugging = on
                    if (signature() != shown) build()
                    main.postDelayed(this, WATCH_MS)
                }
            }.start()
        }
    }

    private fun signature(): String = listOf(
        prefs.tokens.size, debugging, Pairing.request?.takeIf { it.answer == null }?.id,
        TvInfo.overlayAllowed(this), TvInfo.usageAccess(this), Device.notificationAccess(this),
        TvInfo.developerOptions(this), prefs.clientAdb, prefs.clientVersion, prefs.rules(),
    ).joinToString()

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
        val root = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(rail(), LinearLayout.LayoutParams(dp(RAIL_DP), ViewGroup.LayoutParams.MATCH_PARENT))
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(48), dp(40), dp(56), dp(48))
            clipChildren = false
            clipToPadding = false
        }
        scroll = ScrollView(this).apply {
            isFillViewport = true
            isVerticalScrollBarEnabled = false
            addView(content)
        }
        root.addView(scroll, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
        setContentView(root)
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        inFront = true
        build()
        if (currentFocus == null) navItems[section]?.requestFocus()
        main.post(watch)
    }

    override fun onPause() {
        super.onPause()
        resumed = false
        inFront = false
        main.removeCallbacks(watch)
    }

    /**
     * The rail and the content take turns: Left (or Back) from the content
     * goes to its section in the rail, Right from the rail into the content.
     */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN) {
            val focus = currentFocus
            val inContent = focus != null && isInside(focus, content)
            when (event.keyCode) {
                KeyEvent.KEYCODE_DPAD_LEFT -> if (inContent) {
                    val next = focus!!.focusSearch(View.FOCUS_LEFT)
                    if (next == null || !isInside(next, content)) {
                        navItems[section]?.requestFocus()
                        return true
                    }
                }
                KeyEvent.KEYCODE_BACK -> if (inContent) {
                    navItems[section]?.requestFocus()
                    scroll.smoothScrollTo(0, 0)
                    return true
                }
                KeyEvent.KEYCODE_DPAD_RIGHT -> if (focus != null && isInside(focus, nav)) {
                    content.getFocusables(View.FOCUS_DOWN).firstOrNull()?.requestFocus()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    private fun isInside(view: View, parent: ViewGroup): Boolean {
        var v: View? = view
        while (v != null) {
            if (v === parent) return true
            v = v.parent as? View
        }
        return false
    }

    // The rail: the brand, the sections, how it's connected

    private fun rail(): View {
        val rail = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(28), dp(36), dp(20), dp(28))
            background = GradientDrawable().apply { setColor(Theme.RAIL) }
            clipChildren = false
            clipToPadding = false
        }
        rail.addView(brand())
        nav = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(28), 0, 0)
            clipChildren = false
            clipToPadding = false
        }
        rail.addView(nav)
        rail.addView(View(this), LinearLayout.LayoutParams(0, 0, 1f))
        railStatus = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        rail.addView(railStatus)
        return rail
    }

    /** The raineworks mark, Google TV's in its corner, and the name. */
    private fun brand(): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        row.addView(Brand.logo(this, 52), LinearLayout.LayoutParams(dp(52), dp(52)))
        val names = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), 0, 0, 0)
        }
        names.addView(text(getString(R.string.app_name), 17f, Theme.semibold(this), Theme.FOREGROUND))
        names.addView(
            text(getString(R.string.app_tagline), 11f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                setPadding(0, dp(2), 0, 0)
            },
        )
        row.addView(names, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        return row
    }

    private fun sections(): List<Section> =
        Section.entries.filter { it != Section.ADB || !prefs.clientAdb }

    /** The sections, built again when which are shown changes (ADB connected). */
    private fun refreshRail() {
        val wanted = sections()
        if (wanted != navItems.keys.toList()) {
            val hadFocus = currentFocus?.let { isInside(it, nav) } == true
            nav.removeAllViews()
            navItems.clear()
            wanted.forEach { navItems[it] = navItem(it) }
            if (section !in wanted) section = Section.HOME
            if (hadFocus) navItems[section]?.requestFocus()
        }
        navItems.forEach { (s, view) -> view.isActivated = s == section }

        railStatus.removeAllViews()
        val paired = prefs.tokens.isNotEmpty()
        railStatus.addView(
            pill(
                getString(if (paired) R.string.pill_paired else R.string.pill_not_paired),
                if (paired) Theme.SUCCESS else Theme.WARNING,
            ),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT),
        )
        railStatus.addView(
            text(getString(R.string.version_line, BuildConfig.VERSION_NAME), 11f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                setPadding(dp(2), dp(10), 0, 0)
            },
        )
    }

    private fun navItem(target: Section): View {
        val colors = ColorStateList(
            arrayOf(intArrayOf(android.R.attr.state_focused), intArrayOf(android.R.attr.state_activated), intArrayOf()),
            intArrayOf(Theme.PRIMARY_FOREGROUND, Theme.FOREGROUND, Theme.MUTED_FOREGROUND),
        )
        val item = LinearLayout(this).apply {
            id = View.generateViewId()
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            isFocusable = true
            isClickable = true
            setPadding(dp(14), dp(11), dp(14), dp(11))
            background = StateListDrawable().apply {
                fun fill(color: Int) = GradientDrawable().apply {
                    setColor(color)
                    cornerRadius = dp(Theme.RADIUS_DP).toFloat()
                }
                addState(intArrayOf(android.R.attr.state_focused), fill(Theme.PRIMARY))
                addState(intArrayOf(android.R.attr.state_activated), fill(Theme.MUTED))
                addState(intArrayOf(), fill(Color.TRANSPARENT))
            }
            // Landing on a section shows it, as the TV's settings do; not focus
            // Android hands the rail while the content's being built again (the
            // control that had it gone), which would switch to Home
            setOnFocusChangeListener { _, focused ->
                if (focused && !rebuilding && section != target) select(target)
            }
            setOnClickListener { content.getFocusables(View.FOCUS_DOWN).firstOrNull()?.requestFocus() }
        }
        item.addView(
            TextView(this).apply {
                text = Icons.glyph(this@MainActivity, target.icon)
                typeface = Icons.typeface(this@MainActivity)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
                setTextColor(colors)
                isDuplicateParentStateEnabled = true
                includeFontPadding = false
            },
        )
        item.addView(
            text(getString(target.title), 15f, Theme.medium(this), Theme.FOREGROUND).apply {
                setTextColor(colors)
                isDuplicateParentStateEnabled = true
                setPadding(dp(14), 0, 0, 0)
            },
        )
        nav.addView(
            item,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(4)
            },
        )
        return item
    }

    private fun select(target: Section) {
        section = target
        scroll.scrollTo(0, 0)
        build()
    }

    // The content: the section's title over its cards

    private fun build() {
        rebuilding = true
        try {
            buildContent()
        } finally {
            rebuilding = false
        }
    }

    private fun buildContent() {
        // Where the remote was in the content, by its place among the focusable controls
        val focusedIndex = content.getFocusables(View.FOCUS_DOWN).indexOf(currentFocus)
        val request = Pairing.request?.takeIf { it.answer == null }
        var focusAllow = false
        if (request != null && request.id != requestShown) {
            // Home Assistant asks to connect: that comes first
            requestShown = request.id
            section = Section.HOME
            focusAllow = true
        }
        shown = signature()
        refreshRail()
        content.removeAllViews()

        content.addView(text(getString(section.title), 28f, Theme.semibold(this), Theme.FOREGROUND))
        content.addView(
            text(getString(section.subtitle), 14f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                setPadding(0, dp(6), 0, dp(24))
                ellipsize = null
            },
        )
        when (section) {
            Section.HOME -> home(request)
            Section.APPS -> apps()
            Section.POPUPS -> popups()
            Section.PERMISSIONS -> permissions()
            Section.ADB -> adb()
            Section.ABOUT -> about()
        }

        if (focusAllow) {
            content.getFocusables(View.FOCUS_DOWN).firstOrNull()?.let { allow -> allow.post { allow.requestFocus() } }
        } else if (focusedIndex >= 0) {
            // Keep the remote's place after a rebuild
            content.getFocusables(View.FOCUS_DOWN).getOrNull(focusedIndex)?.requestFocus()
        }
    }

    /** How it's going: connected or not, setting up, anything that needs a look. */
    private fun home(request: Pairing.Request?) {
        request?.let { requestCard(it) }
        val paired = prefs.tokens.isNotEmpty()
        val missing = listOf(
            TvInfo.overlayAllowed(this), Device.notificationAccess(this), TvInfo.usageAccess(this),
        ).count { !it }
        hero(
            when {
                !paired -> "mdi:television" to Theme.WARNING
                missing > 0 -> "mdi:alert-circle-outline" to Theme.WARNING
                else -> "mdi:check" to Theme.SUCCESS
            },
            getString(
                when {
                    !paired -> R.string.hero_setup_title
                    missing > 0 -> R.string.hero_attention_title
                    else -> R.string.hero_ready_title
                },
            ),
            when {
                !paired -> getString(R.string.hero_setup_text)
                missing > 0 -> resources.getQuantityString(R.plurals.hero_attention_text, missing, missing)
                prefs.clientAdb -> getString(R.string.hero_ready_adb)
                else -> getString(R.string.hero_ready_app)
            },
        ) { body ->
            if (paired && missing > 0) {
                button(body, getString(R.string.review_permissions), primary = true) {
                    select(Section.PERMISSIONS)
                    content.getFocusables(View.FOCUS_DOWN).firstOrNull()?.requestFocus()
                }
            }
        }
        if (!paired) setupCard()
        card(getString(R.string.status_title)) {
            row(it, getString(R.string.status_home_assistant), when {
                !paired -> getString(R.string.status_not_paired)
                prefs.clientAdb -> getString(R.string.status_paired_adb)
                else -> getString(R.string.status_paired_app)
            })
            if (prefs.clientVersion.isNotEmpty()) row(it, getString(R.string.status_integration), prefs.clientVersion)
            row(it, getString(R.string.status_address), "${ipAddress() ?: "?"}:${ApiServer.PORT}")
            row(it, getString(R.string.status_updates), getString(if (prefs.clientAdb) R.string.updates_auto else R.string.updates_store))
        }
    }

    /** A card led by a big round icon: the state of things, in a sentence. */
    private fun hero(icon: Pair<String, Int>, title: String, value: String, fill: (LinearLayout) -> Unit = {}) {
        val card = surfaceCard()
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            clipChildren = false
            clipToPadding = false
        }
        row.addView(
            TextView(this).apply {
                text = Icons.glyph(this@MainActivity, icon.first)
                typeface = Icons.typeface(this@MainActivity)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 28f)
                setTextColor(icon.second)
                gravity = Gravity.CENTER
                includeFontPadding = false
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Theme.withAlpha(icon.second, 40))
                }
            },
            LinearLayout.LayoutParams(dp(60), dp(60)),
        )
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), 0, 0, 0)
            clipChildren = false
            clipToPadding = false
        }
        texts.addView(text(title, 20f, Theme.semibold(this), Theme.FOREGROUND))
        texts.addView(
            text(value, 14f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                ellipsize = null
                setPadding(0, dp(6), 0, 0)
                setLineSpacing(0f, 1.15f)
            },
        )
        fill(texts)
        row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        card.addView(row)
        addCard(card)
    }

    /**
     * Each app: whether Home Assistant lists it (its app list, its button),
     * and whether pop-ups show over it. The inputs' pop-ups under them.
     */
    private fun apps() {
        card(getString(R.string.apps_card), getString(R.string.apps_card_text)) { body ->
            columns(body, getString(R.string.column_home_assistant), getString(R.string.column_popups))
            TvInfo.apps(this).filter { app -> app.packageName != packageName }.forEach { app ->
                val row = itemRow(body, app.name, appIcon(app.packageName))
                switchCell(row, app.packageName !in prefs.hiddenApps, getString(R.string.column_home_assistant)) { on ->
                    prefs.hiddenApps = if (on) prefs.hiddenApps - app.packageName else prefs.hiddenApps + app.packageName
                    rulesChanged()
                }
                switchCell(row, app.packageName !in prefs.blockedApps, getString(R.string.column_popups)) { on ->
                    prefs.blockedApps = if (on) prefs.blockedApps - app.packageName else prefs.blockedApps + app.packageName
                    rulesChanged()
                }
            }
        }
        card(getString(R.string.inputs_card), getString(R.string.inputs_card_text)) { body ->
            val inputs = TvInfo.inputs(this)
            if (inputs.isEmpty()) {
                muted(body, getString(R.string.no_inputs))
                return@card
            }
            columns(body, getString(R.string.column_home_assistant), getString(R.string.column_popups))
            inputs.forEach { input ->
                val row = itemRow(body, input.name, null, "mdi:video-input-hdmi")
                switchCell(row, input.id !in prefs.hiddenInputs, getString(R.string.column_home_assistant)) { on ->
                    prefs.hiddenInputs = if (on) prefs.hiddenInputs - input.id else prefs.hiddenInputs + input.id
                    rulesChanged()
                }
                switchCell(row, input.id !in prefs.blockedInputs, getString(R.string.column_popups)) { on ->
                    prefs.blockedInputs = if (on) prefs.blockedInputs - input.id else prefs.blockedInputs + input.id
                    rulesChanged()
                }
            }
        }
        card(getString(R.string.when_blocked), getString(R.string.when_blocked_text)) {
            chips(
                it,
                listOf(
                    Prefs.WHEN_BLOCKED_PANEL to getString(R.string.when_blocked_panel),
                    Prefs.WHEN_BLOCKED_DROP to getString(R.string.when_blocked_drop),
                ),
                prefs.whenBlocked,
            ) { value ->
                prefs.whenBlocked = value
                rulesChanged()
            }
        }
    }

    /** Home Assistant hears of a change at once; the screen knows it made it. */
    private fun rulesChanged() {
        Events.emit("rules", prefs.rules())
        shown = signature()
    }

    /** Pop-ups' size and place when a notification doesn't say, and a test. */
    private fun popups() {
        card(getString(R.string.default_size)) {
            chips(
                it,
                NotificationRequest.SIZES.map { size -> size to getString(sizeName(size)) },
                prefs.defaultSize,
            ) { size ->
                prefs.defaultSize = size
                rulesChanged()
            }
        }
        card(getString(R.string.default_position), getString(positionName(prefs.defaultPosition))) { positionPicker(it) }
        card(getString(R.string.try_title)) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                clipChildren = false
                clipToPadding = false
            }
            it.addView(row)
            button(row, getString(R.string.test_button), primary = true) {
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
            button(row, getString(R.string.clear_button)) {
                Notifier.dismiss(this, null)
                Toast.makeText(this, R.string.cleared, Toast.LENGTH_SHORT).show()
            }
        }
    }

    /** The screen in small, a spot for each place a pop-up can be: the picked one filled. */
    private fun positionPicker(parent: LinearLayout) {
        val screen = FrameLayout(this).apply {
            background = Theme.surface(this@MainActivity, Theme.BACKGROUND, 12)
            setPadding(dp(14), dp(14), dp(14), dp(14))
            clipChildren = false
            clipToPadding = false
        }
        listOf(
            "top_left" to (Gravity.TOP or Gravity.START), "top" to (Gravity.TOP or Gravity.CENTER_HORIZONTAL),
            "top_right" to (Gravity.TOP or Gravity.END), "center" to Gravity.CENTER,
            "bottom_left" to (Gravity.BOTTOM or Gravity.START), "bottom" to (Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL),
            "bottom_right" to (Gravity.BOTTOM or Gravity.END),
        ).forEach { (position, gravity) ->
            val picked = position == prefs.defaultPosition
            screen.addView(
                View(this).apply {
                    id = View.generateViewId()
                    isFocusable = true
                    isClickable = true
                    contentDescription = getString(positionName(position))
                    Theme.lift(this, 1.08f)
                    background = Theme.focusable(
                        this@MainActivity,
                        if (picked) Theme.PRIMARY else Theme.withAlpha(Color.WHITE, 14),
                        8,
                        if (picked) Theme.PRIMARY else Theme.withAlpha(Color.WHITE, 40),
                    )
                    setOnClickListener {
                        prefs.defaultPosition = position
                        rulesChanged()
                        build()
                    }
                },
                FrameLayout.LayoutParams(dp(96 + Theme.FOCUS_GAP_DP * 2), dp(44 + Theme.FOCUS_GAP_DP * 2), gravity),
            )
        }
        parent.addView(
            screen,
            LinearLayout.LayoutParams(dp(400), dp(225)).apply { topMargin = dp(6) },
        )
    }

    private fun permissions() {
        card(getString(R.string.permissions_card), getString(R.string.permissions_card_text)) {
            permissionRow(
                it,
                getString(R.string.permission_overlay),
                getString(R.string.permission_overlay_why),
                TvInfo.overlayAllowed(this),
                Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
            )
            permissionRow(
                it,
                getString(R.string.permission_notifications),
                getString(R.string.permission_notifications_why),
                Device.notificationAccess(this),
                Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS),
            )
            permissionRow(
                it,
                getString(R.string.permission_usage),
                getString(R.string.permission_usage_why),
                TvInfo.usageAccess(this),
                Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS),
            )
        }
    }

    /** Who made it, its version, and forgetting Home Assistant. */
    private fun about() {
        card(getString(R.string.about_card)) {
            row(it, getString(R.string.about_version), BuildConfig.VERSION_NAME)
            row(it, getString(R.string.about_build), BuildConfig.GIT_SHA)
            row(it, getString(R.string.about_device), TvInfo.deviceName(this))
            muted(it, getString(R.string.about_privacy))
            muted(it, getString(R.string.about_disclaimer))
        }
        card(getString(R.string.pairing_section), getString(R.string.pairing_section_text)) {
            button(it, getString(R.string.forget_button), destructive = true) {
                prefs.forgetAll()
                Toast.makeText(this, R.string.forgotten, Toast.LENGTH_SHORT).show()
                build()
            }
        }
    }

    /**
     * Setting up, while Home Assistant isn't paired: a QR code to the
     * integration in the Home Assistant Marketplace, then adding the TV in Home Assistant, which asks
     * here to connect.
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
                    setImageBitmap(Qr.bitmap(Qr.MARKETPLACE_URL, dp(152)))
                    background = Theme.surface(this@MainActivity, Color.WHITE, 12, Color.WHITE)
                    setPadding(dp(10), dp(10), dp(10), dp(10))
                    contentDescription = getString(R.string.setup_qr)
                },
                LinearLayout.LayoutParams(dp(172), dp(172)),
            )
            val steps = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(24), 0, 0, 0)
                clipChildren = false
                clipToPadding = false
            }
            step(steps, 1, getString(R.string.setup_marketplace_title), getString(R.string.setup_marketplace_text))
            step(steps, 2, getString(R.string.setup_add_title), getString(R.string.setup_add_text))
            row.addView(steps, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            body.addView(row)
        }
    }

    /** Home Assistant asks to connect: Allow, or not. */
    private fun requestCard(request: Pairing.Request) {
        card(getString(R.string.pair_ask_title), getString(R.string.pair_ask_text, request.name, request.address), highlight = true) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                clipChildren = false
                clipToPadding = false
            }
            it.addView(row)
            button(row, getString(R.string.pair_allow), primary = true) { Pairing.answer(this, true); build() }
            button(row, getString(R.string.pair_deny)) { Pairing.answer(this, false); build() }
        }
    }

    /**
     * More with ADB: what it adds, and how to turn it on, each step's state
     * shown as it changes. Gone once Home Assistant connects over ADB.
     */
    private fun adb() {
        card(getString(R.string.adb_gains_title)) { body ->
            listOf(
                R.string.adb_gain_updates, R.string.adb_gain_remote, R.string.adb_gain_power,
                R.string.adb_gain_input, R.string.adb_gain_permissions,
            ).forEach { gain -> bullet(body, getString(gain)) }
        }
        card(getString(R.string.adb_steps_title)) { body ->
            val on = debugging
            // Debugging on means developer options are, whatever the flag says
            val developer = TvInfo.developerOptions(this) || on == true
            val steps = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, dp(4), 0, 0)
                clipChildren = false
                clipToPadding = false
            }
            step(
                steps, 1, getString(R.string.adb_step_developer), getString(R.string.adb_step_developer_text),
                if (developer) getString(R.string.setup_on) to Theme.SUCCESS else getString(R.string.setup_off) to Theme.WARNING,
            )
            if (!developer) {
                button(steps, getString(R.string.adb_open_about), primary = true, indent = true) {
                    open(Intent(Settings.ACTION_DEVICE_INFO_SETTINGS))
                }
            }
            step(
                steps, 2, getString(R.string.setup_debugging_title), getString(R.string.setup_debugging_text),
                when (on) {
                    null -> null
                    true -> getString(R.string.setup_on) to Theme.SUCCESS
                    false -> getString(R.string.setup_off) to Theme.WARNING
                },
            )
            if (developer && on == false) {
                button(steps, getString(R.string.setup_open_settings), primary = true, indent = true) {
                    open(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))
                }
            }
            step(steps, 3, getString(R.string.adb_step_connect), getString(R.string.adb_step_connect_text))
            body.addView(steps)
        }
    }

    private fun open(settings: Intent) {
        if (settings.resolveActivity(packageManager) != null) {
            startActivity(settings)
        } else {
            Toast.makeText(this, R.string.permission_unavailable, Toast.LENGTH_LONG).show()
        }
    }

    // Pieces

    /** A numbered step: its title (and a status pill), the text under it. */
    private fun step(parent: LinearLayout, number: Int, title: String, value: String, status: Pair<String, Int>? = null) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
            setPadding(0, if (parent.childCount == 0) 0 else dp(18), 0, 0)
        }
        row.addView(
            text(number.toString(), 13f, Theme.semibold(this), Theme.FOREGROUND).apply {
                gravity = Gravity.CENTER
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Theme.MUTED)
                }
            },
            LinearLayout.LayoutParams(dp(28), dp(28)),
        )
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(4), 0, 0)
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
                ellipsize = null
                setPadding(0, dp(5), 0, 0)
                setLineSpacing(0f, 1.2f)
            },
        )
        row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        parent.addView(row)
    }

    private fun surfaceCard(highlight: Boolean = false): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Theme.surface(
                this@MainActivity, Theme.CARD, 14,
                if (highlight) Theme.withAlpha(Theme.INFO, 140) else Theme.BORDER,
            )
            setPadding(dp(26), dp(22), dp(26), dp(24))
            // Rows reach into the padding, their focus ring with them
            clipChildren = false
            clipToPadding = false
        }

    private fun addCard(card: View) {
        content.addView(
            card,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(16)
            },
        )
    }

    /** A card: a header (title, a line under it) over its rows. */
    private fun card(title: String, subtitle: String? = null, highlight: Boolean = false, fill: (LinearLayout) -> Unit) {
        val card = surfaceCard(highlight)
        card.addView(text(title, 17f, Theme.semibold(this), Theme.FOREGROUND))
        subtitle?.let {
            card.addView(
                text(it, 13f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                    ellipsize = null
                    setPadding(0, dp(4), 0, 0)
                    setLineSpacing(0f, 1.15f)
                },
            )
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(12), 0, 0)
            clipChildren = false
            clipToPadding = false
        }
        fill(body)
        card.addView(body)
        addCard(card)
    }

    private fun row(parent: LinearLayout, name: String, value: String) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(9), 0, dp(9))
        }
        row.addView(text(name, 14f, Theme.regular(this), Theme.MUTED_FOREGROUND), LinearLayout.LayoutParams(dp(180), ViewGroup.LayoutParams.WRAP_CONTENT))
        row.addView(
            text(value, 14f, Theme.medium(this), Theme.FOREGROUND).apply { ellipsize = null },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        parent.addView(row)
        if (parent.childCount > 1) row.background = divider()
    }

    /** A hairline along a row's top. */
    private fun divider(): Drawable = object : Drawable() {
        private val paint = Paint().apply { color = Theme.BORDER }
        override fun draw(canvas: Canvas) {
            canvas.drawRect(bounds.left.toFloat(), bounds.top.toFloat(), bounds.right.toFloat(), bounds.top + dp(1).toFloat(), paint)
        }
        override fun setAlpha(alpha: Int) = Unit
        override fun setColorFilter(colorFilter: android.graphics.ColorFilter?) = Unit
        @Deprecated("Deprecated in Java")
        override fun getOpacity(): Int = android.graphics.PixelFormat.TRANSLUCENT
    }

    private fun permissionRow(parent: LinearLayout, name: String, why: String, allowed: Boolean, settings: Intent) {
        val row = focusRow(parent, enabled = !allowed) { open(settings) }
        val texts = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        texts.addView(text(name, 15f, Theme.medium(this), Theme.FOREGROUND))
        texts.addView(
            text(why, 13f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                ellipsize = null
                setPadding(0, dp(4), dp(16), 0)
            },
        )
        row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(
            pill(
                getString(if (allowed) R.string.allowed else R.string.not_allowed),
                if (allowed) Theme.SUCCESS else Theme.WARNING,
            ),
        )
    }

    /** The switches' column names, over their columns. */
    private fun columns(parent: LinearLayout, first: String?, second: String) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(6))
        }
        row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))
        listOf(first, second).forEach { name ->
            row.addView(
                text((name ?: "").uppercase(), 10f, Theme.semibold(this), Theme.MUTED_FOREGROUND).apply {
                    letterSpacing = 0.08f
                    gravity = Gravity.CENTER
                },
                LinearLayout.LayoutParams(dp(COLUMN_DP), ViewGroup.LayoutParams.WRAP_CONTENT),
            )
        }
        parent.addView(row)
    }

    /** An app's or input's row: its icon and name, its switches added after. */
    private fun itemRow(parent: LinearLayout, name: String, icon: Drawable?, glyph: String = "mdi:apps"): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(4), 0, dp(4))
            clipChildren = false
            clipToPadding = false
        }
        if (parent.childCount > 1) row.background = divider()
        row.addView(
            if (icon != null) {
                ImageView(this).apply {
                    setImageDrawable(icon)
                    scaleType = ImageView.ScaleType.FIT_CENTER
                }
            } else {
                TextView(this).apply {
                    text = Icons.glyph(this@MainActivity, glyph)
                    typeface = Icons.typeface(this@MainActivity)
                    setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
                    setTextColor(Theme.MUTED_FOREGROUND)
                    gravity = Gravity.CENTER
                    background = Theme.surface(this@MainActivity, Theme.MUTED, 8, Color.TRANSPARENT)
                }
            },
            LinearLayout.LayoutParams(dp(32), dp(32)),
        )
        row.addView(
            text(name, 15f, Theme.medium(this), Theme.FOREGROUND).apply {
                maxLines = 1
                setPadding(dp(14), 0, dp(8), 0)
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        parent.addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return row
    }

    private fun appIcon(packageName: String): Drawable? = appIcons.getOrPut(packageName) {
        try {
            packageManager.getApplicationIcon(packageName)
        } catch (e: PackageManager.NameNotFoundException) {
            null
        }
    }

    /** A switch the remote lands on (its column), flipped with OK. */
    private fun switchCell(row: LinearLayout, on: Boolean, description: String, onChange: (Boolean) -> Unit) {
        val toggle = Toggle(this, on)
        row.addView(
            FrameLayout(this).apply {
                id = View.generateViewId()
                isFocusable = true
                isClickable = true
                contentDescription = description
                background = Theme.focusable(this@MainActivity, Color.TRANSPARENT, 999, Color.TRANSPARENT)
                setOnClickListener {
                    toggle.on = !toggle.on
                    onChange(toggle.on)
                }
                addView(toggle, FrameLayout.LayoutParams(dp(46), dp(26), Gravity.CENTER))
            },
            LinearLayout.LayoutParams(dp(COLUMN_DP), dp(48)),
        )
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
                background = Theme.focusable(this@MainActivity, Color.TRANSPARENT, 10, Color.TRANSPARENT)
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
            clipChildren = false
            clipToPadding = false
            // The chips' focus gap lines their edge up with the text above
            translationX = -dp(Theme.FOCUS_GAP_DP).toFloat()
        }
        options.forEach { (value, name) ->
            val picked = value == selected
            row.addView(
                text(name, 14f, Theme.medium(this), if (picked) Theme.PRIMARY_FOREGROUND else Theme.FOREGROUND).apply {
                    id = View.generateViewId()
                    gravity = Gravity.CENTER
                    isFocusable = true
                    isClickable = true
                    setPadding(dp(22), dp(14), dp(22), dp(14))
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

    private fun button(
        parent: LinearLayout,
        name: String,
        primary: Boolean = false,
        destructive: Boolean = false,
        indent: Boolean = false,
        onClick: () -> Unit,
    ) {
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
                topMargin = dp(12)
                // Under a step's text, past its number
                marginStart = if (indent) dp(42) - dp(Theme.FOCUS_GAP_DP) else -dp(Theme.FOCUS_GAP_DP)
                marginEnd = dp(6)
            },
        )
    }

    private fun bullet(parent: LinearLayout, value: String) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.TOP
            setPadding(0, dp(5), 0, dp(5))
        }
        row.addView(
            TextView(this).apply {
                text = Icons.glyph(this@MainActivity, "mdi:check")
                typeface = Icons.typeface(this@MainActivity)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
                setTextColor(Theme.SUCCESS)
                includeFontPadding = false
            },
        )
        row.addView(
            text(value, 14f, Theme.regular(this), Theme.FOREGROUND).apply {
                ellipsize = null
                setPadding(dp(12), 0, 0, 0)
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        parent.addView(row)
    }

    private fun muted(parent: LinearLayout, value: String) {
        parent.addView(
            text(value, 13f, Theme.regular(this), Theme.MUTED_FOREGROUND).apply {
                ellipsize = null
                setPadding(0, dp(10), 0, 0)
                setLineSpacing(0f, 1.15f)
            },
        )
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
        /** The screen is in front: it shows a pairing request itself. */
        @Volatile var inFront = false
        private const val WATCH_MS = 3000L
        private const val RAIL_DP = 272
        // An app row's switch columns
        private const val COLUMN_DP = 128
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
            val radius = height / 2f
            rect.set(0f, 0f, width.toFloat(), height.toFloat())
            paint.color = if (on) Theme.SUCCESS else Theme.SWITCH_OFF
            canvas.drawRoundRect(rect, radius, radius, paint)
            val inset = height * 0.14f
            val thumb = height - inset * 2
            val left = if (on) width - inset - thumb else inset
            rect.set(left, inset, left + thumb, inset + thumb)
            paint.color = if (on) Color.WHITE else Theme.MUTED_FOREGROUND
            canvas.drawOval(rect, paint)
        }
    }
}

package com.raineworks.tvbridge

import android.content.Context
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * Shows a notification as asked: a pop-up over whatever's on screen (an app
 * or an HDMI input), in the notification panel, or both, unless a rule says
 * not to pop up over what's on screen now.
 */
object Notifier {
    /** This run of the app: Home Assistant shows its live notifications again when it changes. */
    val instance: String = UUID.randomUUID().toString()

    private val tickets = AtomicLong()
    private val latest = ConcurrentHashMap<String, Long>()
    @Volatile private var dismissedAllAt = 0L

    /**
     * A ticket for a request: it's shown only while it's still the latest
     * for its tag, so an image that loads late can't bring back a pop-up
     * that was dismissed or updated meanwhile.
     */
    private fun issue(tag: String?): Long = tickets.incrementAndGet().also { if (tag != null) latest[tag] = it }

    fun isCurrent(tag: String?, ticket: Long): Boolean =
        ticket > dismissedAllAt && (tag == null || latest[tag] == ticket)

    data class Outcome(
        val popup: Boolean,
        val panel: Boolean,
        val blockedBy: String?,
        val reason: String?,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("popup", popup)
            .put("panel", panel)
            .put("blocked_by", blockedBy ?: JSONObject.NULL)
            .put("reason", reason ?: JSONObject.NULL)
    }

    /** Which rule (if any) keeps a pop-up off the screen now: "app:<pkg>" / "input:<id>". */
    fun blockingRule(prefs: Prefs, app: String?, input: String?): String? {
        if (input != null && input in prefs.blockedInputs) return "input:$input"
        if (app != null && app in prefs.blockedApps) return "app:$app"
        return null
    }

    fun handle(context: Context, request: NotificationRequest): Outcome {
        val prefs = Prefs(context)
        var popup = request.popup
        var panel = request.panel
        var blockedBy: String? = null
        var reason: String? = null
        if (popup && !request.ignoreRules) {
            // What's on screen: Home Assistant's word for it (it knows the
            // input over ADB), else the app in front (usage access)
            val app = request.contextApp ?: TvInfo.foregroundApp(context)
            blockedBy = blockingRule(prefs, app, request.contextInput)
            if (blockedBy != null) {
                popup = false
                reason = "blocked"
                if ((request.whenBlocked ?: prefs.whenBlocked) == Prefs.WHEN_BLOCKED_PANEL) {
                    panel = true
                }
            }
        }
        if (popup && !TvInfo.overlayAllowed(context)) {
            popup = false
            panel = true
            reason = "overlay_not_allowed"
        }
        val ticket = issue(request.tag)
        val tag = request.tag
        // An update the screen or the panel no longer gets takes its old one down
        if (popup) Overlay.get(context).show(request, ticket) else if (tag != null) Overlay.get(context).dismiss(tag)
        if (panel) Notifications.post(context, request, ticket) else if (tag != null) Notifications.cancel(context, tag)
        return Outcome(popup, panel, blockedBy, reason)
    }

    /** Takes a notification (by its tag), or all of them, off the screen and out of the panel. */
    fun dismiss(context: Context, tag: String?) {
        if (tag == null) {
            dismissedAllAt = tickets.incrementAndGet()
            latest.clear()
            Overlay.get(context).dismissAll()
        } else {
            latest[tag] = tickets.incrementAndGet()
            Overlay.get(context).dismiss(tag)
        }
        Notifications.cancel(context, tag)
    }
}

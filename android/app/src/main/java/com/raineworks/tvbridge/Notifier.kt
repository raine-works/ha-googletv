package com.raineworks.tvbridge

import android.content.Context
import org.json.JSONObject

/**
 * Shows a notification as asked: a pop-up over whatever's on screen (an app
 * or an HDMI input), in the notification panel, or both, unless a rule says
 * not to pop up over what's on screen now.
 */
object Notifier {
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
        if (popup) Overlay.get(context).show(request)
        if (panel) Notifications.post(context, request)
        return Outcome(popup, panel, blockedBy, reason)
    }
}

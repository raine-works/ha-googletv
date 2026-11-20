package com.raineworks.tvbridge

import android.content.Context
import org.json.JSONObject

/** A notification's button pressed (on a pop-up or in the panel). */
object Actions {
    /** The "Allow Home Assistant to connect?" question's tag. */
    const val PAIR_TAG = "__pair__"
    const val ALLOW = "allow"
    const val DENY = "deny"

    fun pressed(context: Context, tag: String, action: String) {
        if (tag == PAIR_TAG) {
            Pairing.answer(context, action == ALLOW)
            return
        }
        Events.emit("notification_action", JSONObject().put("tag", tag).put("action", action))
        Notifier.dismiss(context, tag)
    }
}

package com.raineworks.tvbridge

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** A button pressed on a notification in the panel: told to Home Assistant, like a pop-up's. */
class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val tag = intent.getStringExtra(EXTRA_TAG) ?: return
        val action = intent.getStringExtra(EXTRA_ACTION) ?: return
        Actions.pressed(context, tag, action)
    }

    companion object {
        private const val EXTRA_TAG = "tag"
        private const val EXTRA_ACTION = "action"

        fun pending(context: Context, tag: String, action: String, index: Int): PendingIntent =
            PendingIntent.getBroadcast(
                context,
                (tag.hashCode() * 31) + index,
                Intent(context, ActionReceiver::class.java).putExtra(EXTRA_TAG, tag).putExtra(EXTRA_ACTION, action),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
    }
}

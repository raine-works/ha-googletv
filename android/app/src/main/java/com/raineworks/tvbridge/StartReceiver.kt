package com.raineworks.tvbridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Starts the service at boot, after an update, or when asked (com.raineworks.tvbridge.START). */
class StartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            ACTION_START,
            -> BridgeService.start(context)
        }
    }

    companion object {
        const val ACTION_START = "com.raineworks.tvbridge.START"
    }
}

package com.raineworks.tvbridge

import android.app.Application

/** Starts the bridge whenever the app's process starts. */
class BridgeApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
        BridgeService.start(this)
    }
}

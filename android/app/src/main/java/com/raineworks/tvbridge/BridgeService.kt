package com.raineworks.tvbridge

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.Log

/**
 * Keeps the local API up while the TV is on (a foreground service, so Google
 * TV doesn't stop it) and announces it on the network for Home Assistant's
 * discovery (_rwtvbridge._tcp).
 */
class BridgeService : Service() {

    private var server: ApiServer? = null
    private var nsd: NsdManager? = null
    private var registration: NsdManager.RegistrationListener? = null

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
        val notification = Notifications.serviceNotification(this, ApiServer.PORT)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(ID, notification)
        }
        server = ApiServer(this, ApiServer.PORT).also {
            try {
                it.start(SOCKET_READ_TIMEOUT_MS, false)
            } catch (e: java.io.IOException) {
                Log.e(TAG, "Couldn't start the API on port ${ApiServer.PORT}", e)
            }
        }
        announce()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        server?.stop()
        registration?.let {
            try {
                nsd?.unregisterService(it)
            } catch (e: IllegalArgumentException) {
                Log.w(TAG, "mDNS registration already gone: $e")
            }
        }
        super.onDestroy()
    }

    private fun announce() {
        val info = NsdServiceInfo().apply {
            serviceName = "Home Assistant Bridge ${TvInfo.deviceName(this@BridgeService)}"
            serviceType = SERVICE_TYPE
            port = ApiServer.PORT
            setAttribute("api", ApiServer.API_VERSION.toString())
            setAttribute("version", BuildConfig.VERSION_NAME)
            setAttribute("id", Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID))
            setAttribute("model", Build.MODEL)
        }
        val listener = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(info: NsdServiceInfo) {
                Log.i(TAG, "Announced as ${info.serviceName}")
            }
            override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) {
                Log.w(TAG, "mDNS registration failed: $code")
            }
            override fun onServiceUnregistered(info: NsdServiceInfo) = Unit
            override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) = Unit
        }
        nsd = getSystemService(NsdManager::class.java)
        try {
            nsd?.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener)
            registration = listener
        } catch (e: RuntimeException) {
            Log.w(TAG, "Couldn't announce the API: $e")
        }
    }

    companion object {
        const val SERVICE_TYPE = "_rwtvbridge._tcp"
        private const val ID = 1
        private const val SOCKET_READ_TIMEOUT_MS = 15_000
        private const val TAG = "TvBridge"

        /** Starts the service (from the app, at boot, after an update, or asked over ADB). */
        fun start(context: Context) {
            try {
                context.startForegroundService(Intent(context, BridgeService::class.java))
            } catch (e: RuntimeException) {
                // Not allowed from the background without the overlay permission
                // (Android 12+); it starts when the app is next opened
                Log.w(TAG, "Couldn't start the service now: $e")
            }
        }
    }
}

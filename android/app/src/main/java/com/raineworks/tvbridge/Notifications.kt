package com.raineworks.tvbridge

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

/** The notification panel: Home Assistant's notifications and the service's own. */
object Notifications {
    const val CHANNEL_SERVICE = "service"
    const val CHANNEL_HOME_ASSISTANT = "home_assistant"
    private var nextId = 1000

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_SERVICE,
                context.getString(R.string.service_channel),
                NotificationManager.IMPORTANCE_MIN,
            ),
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_HOME_ASSISTANT,
                context.getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_DEFAULT,
            ),
        )
    }

    private fun allowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    /** A notification in the panel, with its image when it has one. */
    fun post(context: Context, request: NotificationRequest) {
        val app = context.applicationContext
        val id = request.tag?.hashCode() ?: synchronized(this) { nextId++ }
        val show = { image: android.graphics.Bitmap? ->
            if (allowed(app)) {
                val builder = Notification.Builder(app, CHANNEL_HOME_ASSISTANT)
                    .setSmallIcon(R.drawable.icon)
                    .setContentTitle(request.title ?: app.getString(R.string.app_name))
                    .setContentText(request.message ?: "")
                    .setAutoCancel(true)
                request.color?.let { builder.setColor(it) }
                if (image != null) {
                    builder.setLargeIcon(image)
                        .setStyle(Notification.BigPictureStyle().bigPicture(image))
                } else if (request.message != null) {
                    builder.setStyle(Notification.BigTextStyle().bigText(request.message))
                }
                app.getSystemService(NotificationManager::class.java).notify(id, builder.build())
            }
        }
        val url = request.imageUrl
        if (url == null) {
            show(null)
        } else {
            Images.load(url, 1024) { bitmap -> show(bitmap) }
        }
    }

    /** The service's own, always there while it runs. */
    fun serviceNotification(context: Context, port: Int): Notification =
        Notification.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.icon)
            .setContentTitle(context.getString(R.string.app_name))
            .setContentText(context.getString(R.string.service_text, port))
            .setOngoing(true)
            .build()
}

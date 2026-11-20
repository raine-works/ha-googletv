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

    private fun id(tag: String): Int = tag.hashCode()

    /**
     * A notification in the panel, with its image when it has one. One with a
     * tag updates the last with that tag in place, without alerting again; a
     * persistent one stays until it's dismissed.
     */
    fun post(context: Context, request: NotificationRequest, ticket: Long) {
        val app = context.applicationContext
        val id = request.tag?.let { id(it) } ?: synchronized(this) { nextId++ }
        val show = { image: android.graphics.Bitmap? ->
            if (allowed(app) && Notifier.isCurrent(request.tag, ticket)) {
                val builder = Notification.Builder(app, CHANNEL_HOME_ASSISTANT)
                    .setSmallIcon(R.drawable.ic_stat_logo)
                    .setContentTitle(request.title ?: app.getString(R.string.app_name))
                    .setContentText(request.message ?: "")
                    .setOnlyAlertOnce(true)
                    .setOngoing(request.persistent)
                    .setAutoCancel(!request.persistent)
                request.color?.let { builder.setColor(it) }
                request.progress?.let { builder.setProgress(100, it, false) }
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

    /** Takes the notification with [tag], or all of Home Assistant's, out of the panel. */
    fun cancel(context: Context, tag: String?) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (tag != null) {
            manager.cancel(id(tag))
        } else {
            manager.activeNotifications
                .filter { it.notification.channelId == CHANNEL_HOME_ASSISTANT }
                .forEach { manager.cancel(it.tag, it.id) }
        }
    }

    /** The service's own, always there while it runs. */
    fun serviceNotification(context: Context, port: Int): Notification =
        Notification.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_stat_logo)
            .setContentTitle(context.getString(R.string.app_name))
            .setContentText(context.getString(R.string.service_text, port))
            .setOngoing(true)
            .build()
}

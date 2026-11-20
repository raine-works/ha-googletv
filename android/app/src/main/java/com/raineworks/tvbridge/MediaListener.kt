package com.raineworks.tvbridge

import android.service.notification.NotificationListenerService

/**
 * Notification access: Android shows other apps' media sessions (what's
 * playing, its title and position) only to an app with it. It reads no
 * notifications.
 */
class MediaListener : NotificationListenerService()

package com.raineworks.tvbridge

import org.json.JSONObject

/** A notification from Home Assistant (POST /api/notify; see protocol/README.md). */
data class NotificationRequest(
    val title: String?,
    val message: String?,
    val imageUrl: String?,
    val videoUrl: String?,
    val mode: String,
    val position: String,
    // 0: until it's dismissed
    val durationS: Int,
    val size: String,
    val color: Int?,
    val mute: Boolean,
    val ignoreRules: Boolean,
    val whenBlocked: String?,
    val tag: String?,
    // "mdi:<name>", or an image URL, in place of the logo
    val icon: String? = null,
    // 0 to 100: a progress bar
    val progress: Int? = null,
    // Buttons: the card takes the remote's focus to offer them
    val actions: List<Action> = emptyList(),
    val contextApp: String?,
    val contextInput: String?,
) {
    val popup: Boolean get() = mode == MODE_POPUP || mode == MODE_BOTH
    val panel: Boolean get() = mode == MODE_PANEL || mode == MODE_BOTH
    val persistent: Boolean get() = durationS == 0

    /** A button on the notification: [id] goes to Home Assistant when it's pressed. */
    data class Action(val id: String, val title: String)

    companion object {
        const val MODE_POPUP = "popup"
        const val MODE_PANEL = "panel"
        const val MODE_BOTH = "both"
        val MODES = setOf(MODE_POPUP, MODE_PANEL, MODE_BOTH)
        val POSITIONS = setOf(
            "top_left", "top", "top_right", "center",
            "bottom_left", "bottom", "bottom_right",
        )
        val SIZES = listOf("compact", "small", "medium", "large")
        const val MAX_ACTIONS = 3

        /**
         * A request from JSON (a bad field is an [IllegalArgumentException]);
         * no position or size: the TV's defaults.
         */
        fun parse(
            json: JSONObject,
            defaultPosition: String = "top_right",
            defaultSize: String = "small",
        ): NotificationRequest {
            fun text(name: String): String? =
                json.optString(name, "").trim().takeIf { it.isNotEmpty() && !json.isNull(name) }

            val title = text("title")
            val message = text("message")
            val imageUrl = text("image_url")
            val videoUrl = text("video_url")
            require(title != null || message != null || imageUrl != null || videoUrl != null) {
                "Nothing to show: give a title, message, image_url or video_url"
            }
            val mode = text("mode") ?: MODE_POPUP
            require(mode in MODES) { "mode must be one of $MODES" }
            val position = text("position") ?: defaultPosition
            require(position in POSITIONS) { "position must be one of $POSITIONS" }
            val size = text("size") ?: defaultSize
            require(size in SIZES) { "size must be one of $SIZES" }
            val actions = json.optJSONArray("actions")?.let { list ->
                require(list.length() <= MAX_ACTIONS) { "At most $MAX_ACTIONS actions" }
                (0 until list.length()).map { i ->
                    val item = list.getJSONObject(i)
                    val id = item.optString("action").trim()
                    val label = item.optString("title").trim()
                    require(Regex("^[A-Za-z0-9_.:-]{1,64}$").matches(id)) { "An action's id: letters, digits, _ . : -" }
                    require(label.isNotEmpty() && label.length <= 40) { "An action's title: 1 to 40 characters" }
                    Action(id, label)
                }
            } ?: emptyList()
            // A card with buttons gives time to choose
            val duration = if (json.has("duration")) json.getDouble("duration").toInt()
            else if (actions.isNotEmpty()) 30 else if (videoUrl != null) 20 else 8
            require(duration in 0..600) { "duration must be 0 (until dismissed) to 600 seconds" }
            val color = text("color")?.let {
                try {
                    android.graphics.Color.parseColor(if (it.startsWith("#")) it else "#$it")
                } catch (e: IllegalArgumentException) {
                    throw IllegalArgumentException("color must be a hex color like #03A9F4")
                }
            }
            val whenBlocked = text("when_blocked")
            require(whenBlocked == null || whenBlocked in setOf(Prefs.WHEN_BLOCKED_PANEL, Prefs.WHEN_BLOCKED_DROP)) {
                "when_blocked must be panel or drop"
            }
            require(imageUrl == null || Regex("^https?://\\S+$", RegexOption.IGNORE_CASE).matches(imageUrl)) {
                "image_url must be an http(s) URL"
            }
            require(videoUrl == null || Regex("^(https?|rtsp)://\\S+$", RegexOption.IGNORE_CASE).matches(videoUrl)) {
                "video_url must be an http(s) or rtsp URL"
            }
            val icon = text("icon")
            require(
                icon == null ||
                    Regex("^mdi:[a-z0-9-]+$").matches(icon) ||
                    Regex("^https?://\\S+$", RegexOption.IGNORE_CASE).matches(icon),
            ) { "icon must be mdi:<name> or an http(s) image URL" }
            val progress = if (json.has("progress") && !json.isNull("progress")) {
                json.getDouble("progress").toInt().also { require(it in 0..100) { "progress must be 0 to 100" } }
            } else {
                null
            }
            val context = json.optJSONObject("context")
            return NotificationRequest(
                title = title,
                message = message,
                imageUrl = imageUrl,
                videoUrl = videoUrl,
                mode = mode,
                position = position,
                durationS = duration,
                size = size,
                color = color,
                mute = json.optBoolean("mute", true),
                ignoreRules = json.optBoolean("ignore_rules", false),
                whenBlocked = whenBlocked,
                tag = text("tag"),
                icon = icon,
                progress = progress,
                actions = actions,
                contextApp = context?.optString("app", "")?.takeIf { it.isNotBlank() },
                contextInput = context?.optString("input", "")?.takeIf { it.isNotBlank() },
            )
        }
    }
}

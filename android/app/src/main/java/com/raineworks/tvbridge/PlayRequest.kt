package com.raineworks.tvbridge

import org.json.JSONObject

/** Media from Home Assistant to play (POST /api/play; see protocol/README.md). */
data class PlayRequest(
    val url: String,
    // "audio", "video" or "image"
    val kind: String,
    val mime: String?,
    val title: String?,
    val artist: String?,
    val imageUrl: String?,
    // Spoken over what's on, which ducks, instead of played full screen
    val announce: Boolean,
    // Shown on a pill while an announcement plays
    val message: String?,
) {
    companion object {
        val KINDS = setOf("audio", "video", "image")
        private val URL = Regex("^(https?|rtsp)://\\S+$", RegexOption.IGNORE_CASE)

        fun parse(json: JSONObject): PlayRequest {
            fun text(name: String): String? =
                json.optString(name, "").trim().takeIf { it.isNotEmpty() && !json.isNull(name) }

            val url = text("url") ?: throw IllegalArgumentException("url is required")
            require(URL.matches(url)) { "url must be an http(s) or rtsp URL" }
            val mime = text("mime")
            val kind = text("kind") ?: when {
                mime?.startsWith("audio/") == true -> "audio"
                mime?.startsWith("image/") == true -> "image"
                else -> "video"
            }
            require(kind in KINDS) { "kind must be one of $KINDS" }
            val imageUrl = text("image_url")
            require(imageUrl == null || URL.matches(imageUrl)) { "image_url must be an http(s) URL" }
            val announce = json.optBoolean("announce", false)
            require(!announce || kind == "audio") { "Only audio can be announced" }
            return PlayRequest(
                url = url,
                kind = kind,
                mime = mime,
                title = text("title"),
                artist = text("artist"),
                imageUrl = imageUrl,
                announce = announce,
                message = text("message"),
            )
        }
    }
}

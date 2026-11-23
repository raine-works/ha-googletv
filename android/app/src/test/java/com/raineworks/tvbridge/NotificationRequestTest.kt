package com.raineworks.tvbridge

import com.raineworks.tvbridge.NotificationRequest.Companion.MAX_ACTIONS
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * What a paired client may ask the TV to show (POST /api/notify), and what it's refused.
 * (No test sets a color: parsing one needs Android's Color, which a JVM unit test doesn't have.)
 */
class NotificationRequestTest {
    private fun parse(json: String) = NotificationRequest.parse(JSONObject(json))

    private fun refused(json: String) {
        assertThrows(IllegalArgumentException::class.java) { parse(json) }
    }

    /** A valid request with [extra] (JSON members, without braces) added. */
    private fun refusedWith(extra: String) = refused("""{"title": "Hi", $extra}""")

    @Test
    fun validRequestIsParsed() {
        val r = parse(
            """{"title": "Door", "message": "Someone's there", "image_url": "https://ha.local/snap.jpg",
               "video_url": "rtsp://cam.local/stream", "mode": "both", "position": "bottom",
               "duration": 45, "size": "large", "mute": false, "ignore_rules": true,
               "when_blocked": "drop", "tag": "door", "icon": "mdi:doorbell", "progress": 50,
               "actions": [{"action": "OPEN_DOOR", "title": "Open"}, {"action": "ignore.me:1", "title": "Ignore"}],
               "context": {"app": "com.example", "input": "hdmi1"},
               "webrtc": {"entity_id": "camera.front_door", "ws_url": "wss://ha.local/api/websocket",
                          "ice_servers": [{"urls": "stun:stun.example:3478"},
                                          {"urls": ["turn:a", "turn:b"], "username": "u", "credential": "c"}]}}""",
        )
        assertEquals("Door", r.title)
        assertEquals("Someone's there", r.message)
        assertEquals("https://ha.local/snap.jpg", r.imageUrl)
        assertEquals("rtsp://cam.local/stream", r.videoUrl)
        assertTrue(r.popup && r.panel)
        assertEquals("bottom", r.position)
        assertEquals(45, r.durationS)
        assertEquals("large", r.size)
        assertEquals(false, r.mute)
        assertEquals(true, r.ignoreRules)
        assertEquals("drop", r.whenBlocked)
        assertEquals("door", r.tag)
        assertEquals("mdi:doorbell", r.icon)
        assertEquals(50, r.progress)
        assertEquals(
            listOf(NotificationRequest.Action("OPEN_DOOR", "Open"), NotificationRequest.Action("ignore.me:1", "Ignore")),
            r.actions,
        )
        assertEquals("com.example", r.contextApp)
        assertEquals("hdmi1", r.contextInput)
        val webrtc = r.webrtc!!
        assertEquals("camera.front_door", webrtc.entityId)
        assertEquals("wss://ha.local/api/websocket", webrtc.wsUrl)
        assertEquals(
            listOf(
                NotificationRequest.IceServer(listOf("stun:stun.example:3478"), null, null),
                NotificationRequest.IceServer(listOf("turn:a", "turn:b"), "u", "c"),
            ),
            webrtc.iceServers,
        )
    }

    @Test
    fun defaultsApply() {
        val r = NotificationRequest.parse(JSONObject("""{"message": "Hi"}"""), "center", "medium")
        assertTrue(r.popup && !r.panel)
        assertEquals("center", r.position)
        assertEquals("medium", r.size)
        assertEquals(8, r.durationS)
        assertTrue(r.mute)
        assertNull(r.progress)
        assertNull(r.icon)
        assertNull(r.webrtc)
        assertEquals(20, parse("""{"video_url": "https://a/b.m3u8"}""").durationS)
        assertEquals(30, parse("""{"title": "Hi", "actions": [{"action": "a", "title": "A"}]}""").durationS)
        assertTrue(parse("""{"title": "Hi", "duration": 0}""").persistent)
        assertEquals("https://a/icon.png", parse("""{"title": "Hi", "icon": "https://a/icon.png"}""").icon)
    }

    @Test
    fun nothingToShowIsRefused() {
        refused("""{}""")
        refused("""{"title": " ", "message": null}""")
    }

    @Test
    fun imageUrlWithAnotherSchemeIsRefused() {
        refusedWith(""""image_url": "file:///sdcard/a.jpg"""")
        refusedWith(""""image_url": "content://com.example/a"""")
        // rtsp is for video only
        refusedWith(""""image_url": "rtsp://cam.local/stream"""")
    }

    @Test
    fun videoUrlWithAnotherSchemeIsRefused() {
        refusedWith(""""video_url": "file:///sdcard/a.mp4"""")
        refusedWith(""""video_url": "content://com.example/a"""")
    }

    @Test
    fun iconOtherThanMdiOrHttpIsRefused() {
        refusedWith(""""icon": "file:///sdcard/icon.png"""")
        refusedWith(""""icon": "content://com.example/icon"""")
        refusedWith(""""icon": "mdi:Bad Name"""")
    }

    @Test
    fun webrtcWithAnotherSchemeOrEntityIsRefused() {
        refused("""{"webrtc": {"entity_id": "camera.door", "ws_url": "http://ha.local/api/websocket"}}""")
        refused("""{"webrtc": {"entity_id": "camera.door", "ws_url": "file:///sdcard/x"}}""")
        refused("""{"webrtc": {"entity_id": "light.kitchen", "ws_url": "ws://ha.local/api/websocket"}}""")
        refused("""{"webrtc": {"entity_id": "camera.door; drop", "ws_url": "ws://ha.local/api/websocket"}}""")
        refused("""{"webrtc": {"ws_url": "ws://ha.local/api/websocket"}}""")
    }

    @Test
    fun badActionIsRefused() {
        refusedWith(""""actions": [{"action": "", "title": "Open"}]""")
        refusedWith(""""actions": [{"action": "open door", "title": "Open"}]""")
        refusedWith(""""actions": [{"action": "${"a".repeat(65)}", "title": "Open"}]""")
        refusedWith(""""actions": [{"action": "open", "title": ""}]""")
        refusedWith(""""actions": [{"action": "open", "title": "${"t".repeat(41)}"}]""")
    }

    @Test
    fun tooManyActionsAreRefused() {
        val actions = (0..MAX_ACTIONS).joinToString(",") { """{"action": "a$it", "title": "A$it"}""" }
        refusedWith(""""actions": [$actions]""")
        val allowed = (1..MAX_ACTIONS).joinToString(",") { """{"action": "a$it", "title": "A$it"}""" }
        assertEquals(MAX_ACTIONS, parse("""{"title": "Hi", "actions": [$allowed]}""").actions.size)
    }

    @Test
    fun durationOutOfRangeIsRefused() {
        refusedWith(""""duration": -1""")
        refusedWith(""""duration": 601""")
        assertEquals(600, parse("""{"title": "Hi", "duration": 600}""").durationS)
    }

    @Test
    fun progressOutOfRangeIsRefused() {
        refusedWith(""""progress": -1""")
        refusedWith(""""progress": 101""")
        assertEquals(0, parse("""{"title": "Hi", "progress": 0}""").progress)
        assertEquals(100, parse("""{"title": "Hi", "progress": 100}""").progress)
    }

    @Test
    fun unknownModePositionSizeOrWhenBlockedIsRefused() {
        refusedWith(""""mode": "fullscreen"""")
        refusedWith(""""position": "left"""")
        refusedWith(""""size": "huge"""")
        refusedWith(""""when_blocked": "queue"""")
    }
}

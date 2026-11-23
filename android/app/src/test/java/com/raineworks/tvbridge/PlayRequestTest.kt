package com.raineworks.tvbridge

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** What a paired client may ask the TV to play (POST /api/play), and what it's refused. */
class PlayRequestTest {
    private fun parse(json: String) = PlayRequest.parse(JSONObject(json))

    private fun refused(json: String) {
        assertThrows(IllegalArgumentException::class.java) { parse(json) }
    }

    @Test
    fun validRequestIsParsed() {
        val r = parse(
            """{"url": " https://ha.local/song.mp3 ", "kind": "audio", "mime": "audio/mpeg",
               "title": "Song", "artist": "Band", "image_url": "http://ha.local/art.jpg",
               "announce": true, "message": "Doorbell"}""",
        )
        assertEquals("https://ha.local/song.mp3", r.url)
        assertEquals("audio", r.kind)
        assertEquals("audio/mpeg", r.mime)
        assertEquals("Song", r.title)
        assertEquals("Band", r.artist)
        assertEquals("http://ha.local/art.jpg", r.imageUrl)
        assertTrue(r.announce)
        assertEquals("Doorbell", r.message)
    }

    @Test
    fun rtspUrlIsAccepted() {
        assertEquals("rtsp://cam.local/stream", parse("""{"url": "rtsp://cam.local/stream"}""").url)
    }

    @Test
    fun kindDefaultsFromMimeThenVideo() {
        assertEquals("audio", parse("""{"url": "http://a/b", "mime": "audio/ogg"}""").kind)
        assertEquals("image", parse("""{"url": "http://a/b", "mime": "image/png"}""").kind)
        val r = parse("""{"url": "http://a/b"}""")
        assertEquals("video", r.kind)
        assertFalse(r.announce)
        assertNull(r.imageUrl)
    }

    @Test
    fun missingUrlIsRefused() {
        refused("""{}""")
        refused("""{"url": ""}""")
        refused("""{"url": "   "}""")
        refused("""{"url": null}""")
    }

    @Test
    fun urlWithAnotherSchemeIsRefused() {
        refused("""{"url": "file:///sdcard/secret.mp4"}""")
        refused("""{"url": "content://com.example/secret"}""")
        refused("""{"url": "javascript:alert(1)"}""")
        refused("""{"url": "https://a/b c"}""")
    }

    @Test
    fun imageUrlWithAnotherSchemeIsRefused() {
        refused("""{"url": "http://a/b", "image_url": "file:///sdcard/art.jpg"}""")
        refused("""{"url": "http://a/b", "image_url": "content://com.example/art"}""")
    }

    @Test
    fun unknownKindIsRefused() {
        refused("""{"url": "http://a/b", "kind": "app"}""")
        refused("""{"url": "http://a/b", "kind": "AUDIO"}""")
    }

    @Test
    fun onlyAudioIsAnnounced() {
        refused("""{"url": "http://a/b", "kind": "video", "announce": true}""")
        refused("""{"url": "http://a/b", "kind": "image", "announce": true}""")
        // No kind and no mime: a video, which can't be announced
        refused("""{"url": "http://a/b", "announce": true}""")
    }
}

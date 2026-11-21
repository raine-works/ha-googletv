package com.raineworks.tvbridge

import android.content.Context
import android.graphics.SurfaceTexture
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.TextureView
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.GlRectDrawer
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RendererCommon
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceEglRenderer
import org.webrtc.VideoTrack
import org.webrtc.audio.JavaAudioDeviceModule
import java.util.concurrent.TimeUnit

/**
 * A camera live over WebRTC on a pop-up, as Home Assistant's own frontend
 * plays one: the app signs in to Home Assistant's websocket (the TV's own
 * read-only user), sends its offer with camera/webrtc/offer, and trades ICE
 * candidates on that subscription. The video draws on the card's
 * [TextureView], so the card's corners clip it. [listener] hears the first
 * frame, or that it failed (the card falls back to HLS). Main thread only.
 */
class LiveCamera(
    private val context: Context,
    private val camera: NotificationRequest.WebRtc,
    private val token: String,
    private var mute: Boolean,
    private val listener: Listener,
) {
    interface Listener {
        fun onFirstFrame()

        /** It didn't start, or stopped: [reason] for Home Assistant's log. */
        fun onFailed(reason: String)
    }

    private val main = Handler(Looper.getMainLooper())
    private var socket: WebSocket? = null
    private var peer: PeerConnection? = null
    private var audio: MediaStreamTrack? = null
    private val renderer = SurfaceEglRenderer("live-${camera.entityId}")
    private var texture: TextureView? = null
    private var surface: SurfaceTexture? = null

    /**
     * Whether it receives the camera's sound: only when it isn't muted. A
     * muted one asks for video alone, so WebRTC never starts playing audio,
     * which crashes natively on some TVs (a Sony on 32-bit ARM, Android 12).
     */
    val receivesAudio = !mute

    private var nextId = 1
    private var offerId = 0
    private var sessionId: String? = null
    // Candidates found before Home Assistant names the session
    private val pending = mutableListOf<IceCandidate>()
    private var started = false
    private var closed = false
    // Home Assistant refused the offer: no session to unsubscribe from
    private var refused = false

    // Not drawing within this long: HLS instead
    private val timeout = Runnable { fail("timeout") }

    fun start(view: TextureView) {
        try {
            Shared.egl
        } catch (e: Throwable) {
            main.post { fail("WebRTC unavailable: $e") }
            return
        }
        renderer.init(
            Shared.egl.eglBaseContext,
            object : RendererCommon.RendererEvents {
                override fun onFirstFrameRendered() {
                    main.post {
                        if (closed || started) return@post
                        started = true
                        main.removeCallbacks(timeout)
                        listener.onFirstFrame()
                    }
                }

                override fun onFrameResolutionChanged(width: Int, height: Int, rotation: Int) = Unit
            },
            EglBase.CONFIG_PLAIN,
            GlRectDrawer(),
        )
        attach(view)
        main.postDelayed(timeout, START_TIMEOUT_MS)
        socket = Shared.http.newWebSocket(Request.Builder().url(camera.wsUrl).build(), signaling)
    }

    /** Draws on [view] from now on (the card was updated in place: the session goes on). */
    fun attach(view: TextureView) {
        if (texture === view) return
        detach()
        texture = view
        // Filled, cropped to the frame, like the clips and the poster
        renderer.setLayoutAspectRatio(16f / 9f)
        val ready = view.surfaceTexture
        if (ready != null) use(ready)
        view.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(st: SurfaceTexture, width: Int, height: Int) = use(st)
            override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, width: Int, height: Int) = Unit
            override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
                if (surface === st) {
                    surface = null
                    // Released once the renderer has let go of it
                    renderer.releaseEglSurface { main.post { st.release() } }
                    return false
                }
                return true
            }

            override fun onSurfaceTextureUpdated(st: SurfaceTexture) = Unit
        }
    }

    private fun use(st: SurfaceTexture) {
        if (surface === st || closed) return
        surface = st
        renderer.createEglSurface(st)
    }

    /**
     * Lets go of the view; [then] once the renderer has (another player may
     * draw on it after).
     *
     * Until the renderer has let go, the view mustn't release its surface:
     * the card coming down destroys it at once, and drawing on a released
     * surface (a frame on WebRTC's render thread) crashes the app. So the
     * view's listener keeps it, and it's released after.
     */
    private fun detach(then: () -> Unit = {}) {
        val view = texture
        val st = surface
        texture = null
        surface = null
        if (st == null) {
            view?.surfaceTextureListener = null
            then()
            return
        }
        var released = false
        var destroyed = false
        view?.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(s: SurfaceTexture, width: Int, height: Int) = Unit
            override fun onSurfaceTextureSizeChanged(s: SurfaceTexture, width: Int, height: Int) = Unit
            override fun onSurfaceTextureUpdated(s: SurfaceTexture) = Unit
            override fun onSurfaceTextureDestroyed(s: SurfaceTexture): Boolean {
                if (s !== st) return true
                destroyed = true
                // Kept until the renderer has let go, then released here
                if (released) st.release()
                return false
            }
        }
        renderer.releaseEglSurface {
            main.post {
                released = true
                if (destroyed) st.release()
                then()
            }
        }
    }

    fun setMute(value: Boolean) {
        mute = value
        audio?.setEnabled(!value)
    }

    /**
     * Ends it: Home Assistant closes the camera's session, then the
     * connection goes; [then] once its view is free for another player.
     */
    fun close(then: () -> Unit = {}) {
        if (closed) return
        closed = true
        main.removeCallbacks(timeout)
        socket?.let { ws ->
            if (offerId != 0 && !refused) {
                ws.send(JSONObject().put("id", nextId++).put("type", "unsubscribe_events").put("subscription", offerId).toString())
            }
            ws.close(1000, null)
        }
        socket = null
        val pc = peer
        peer = null
        detach(then)
        // Off the main thread: closing a peer connection waits on WebRTC's threads
        Shared.worker.execute {
            pc?.dispose()
            renderer.release()
        }
    }

    private fun fail(reason: String) {
        if (closed) return
        Log.w(TAG, "WebRTC for ${camera.entityId}: $reason")
        close { listener.onFailed(reason) }
    }

    // Signaling, on Home Assistant's websocket

    private val signaling = object : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, text: String) {
            main.post { if (!closed) handle(JSONObject(text)) }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            main.post { fail("websocket: ${t.message}") }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            main.post { if (!started) fail("websocket closed") }
        }
    }

    private fun send(message: JSONObject) {
        socket?.send(message.toString())
    }

    private fun handle(message: JSONObject) {
        when (message.optString("type")) {
            "auth_required" -> send(JSONObject().put("type", "auth").put("access_token", token))
            "auth_ok" -> offer()
            "auth_invalid" -> fail("auth_invalid")
            "result" -> if (message.optInt("id") == offerId && !message.optBoolean("success")) {
                refused = true
                fail(message.optJSONObject("error")?.optString("message") ?: "offer refused")
            }
            "event" -> if (message.optInt("id") == offerId) event(message.getJSONObject("event"))
        }
    }

    private fun event(event: JSONObject) {
        val pc = peer ?: return
        when (event.optString("type")) {
            "session" -> {
                sessionId = event.getString("session_id")
                pending.forEach { sendCandidate(it) }
                pending.clear()
            }
            "answer" -> pc.setRemoteDescription(
                Sdp("answer") {},
                SessionDescription(SessionDescription.Type.ANSWER, event.getString("answer")),
            )
            "candidate" -> {
                val candidate = event.getJSONObject("candidate")
                pc.addIceCandidate(
                    IceCandidate(
                        candidate.optString("sdpMid", "0"),
                        candidate.optInt("sdpMLineIndex", 0),
                        candidate.getString("candidate"),
                    ),
                )
            }
            "error" -> {
                refused = true
                fail("${event.optString("code")}: ${event.optString("message")}")
            }
        }
    }

    private fun sendCandidate(candidate: IceCandidate) {
        send(
            JSONObject()
                .put("id", nextId++)
                .put("type", "camera/webrtc/candidate")
                .put("entity_id", camera.entityId)
                .put("session_id", sessionId)
                .put(
                    "candidate",
                    JSONObject().put("candidate", candidate.sdp).put("sdpMid", candidate.sdpMid)
                        .put("sdpMLineIndex", candidate.sdpMLineIndex),
                ),
        )
    }

    /** A receive-only peer (video and audio), its offer sent once it's made. */
    private fun offer() {
        val servers = camera.iceServers.map { server ->
            PeerConnection.IceServer.builder(server.urls).apply {
                server.username?.let { setUsername(it) }
                server.credential?.let { setPassword(it) }
            }.createIceServer()
        }
        val config = PeerConnection.RTCConfiguration(servers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
        }
        val factory = try {
            Shared.factory(context)
        } catch (e: Throwable) {
            // WebRTC's native code isn't there for this TV's CPU
            return fail("WebRTC unavailable: $e")
        }
        val pc = factory.createPeerConnection(config, observer) ?: return fail("no peer connection")
        peer = pc
        val receive = RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY)
        val video = pc.addTransceiver(MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO, receive)
        // No H.265: this WebRTC build crashes natively setting up an H.265
        // receiver (a Sony on 32-bit ARM, as go2rtc sent it), and the TV's one
        // hardware H.265 decoder is usually the show's. A camera that sends
        // only H.265 is refused ("codecs not matched") and plays over HLS, on
        // the TV's software decoder; an H.264 one is live in under a second.
        val codecs = factory.getRtpReceiverCapabilities(MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO).codecs
        video.setCodecPreferences(codecs.filter { it.name != "H265" })
        if (receivesAudio) pc.addTransceiver(MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO, receive)
        pc.createOffer(
            Sdp("offer") { offer ->
                pc.setLocalDescription(
                    Sdp("local description") {
                        main.post {
                            if (closed) return@post
                            offerId = nextId++
                            send(
                                JSONObject()
                                    .put("id", offerId)
                                    .put("type", "camera/webrtc/offer")
                                    .put("entity_id", camera.entityId)
                                    .put("offer", offer!!.description),
                            )
                        }
                    },
                    offer,
                )
            },
            MediaConstraints(),
        )
    }

    private val observer = object : PeerConnection.Observer {
        override fun onIceCandidate(candidate: IceCandidate) {
            main.post {
                if (closed) return@post
                if (sessionId == null) pending.add(candidate) else sendCandidate(candidate)
            }
        }

        override fun onTrack(transceiver: RtpTransceiver) {
            val track = transceiver.receiver.track() ?: return
            main.post {
                if (closed) return@post
                when (track) {
                    is VideoTrack -> track.addSink(renderer)
                    else -> {
                        audio = track
                        track.setEnabled(!mute)
                    }
                }
            }
        }

        override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
            if (state == PeerConnection.PeerConnectionState.FAILED) main.post { fail("connection failed") }
        }

        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onDataChannel(channel: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
    }

    /** An SDP step: [done] with the description made (or null), a failure fails the session. */
    private inner class Sdp(private val step: String, private val done: (SessionDescription?) -> Unit) : SdpObserver {
        override fun onCreateSuccess(description: SessionDescription) = done(description)
        override fun onSetSuccess() = done(null)
        override fun onCreateFailure(error: String?) {
            main.post { fail("$step: $error") }
        }

        override fun onSetFailure(error: String?) {
            main.post { fail("$step: $error") }
        }
    }

    /** One WebRTC factory, EGL context and HTTP client for the app. */
    private object Shared {
        val egl: EglBase by lazy { EglBase.create() }
        val http: OkHttpClient by lazy {
            OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).build()
        }
        val worker: java.util.concurrent.ExecutorService = java.util.concurrent.Executors.newSingleThreadExecutor()
        private var factory: PeerConnectionFactory? = null

        fun factory(context: Context): PeerConnectionFactory = factory ?: run {
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions(),
            )
            // WebRTC's own warnings and errors in the log (adb logcat), for a camera that won't play
            org.webrtc.Logging.enableLogToDebugOutput(org.webrtc.Logging.Severity.LS_WARNING)
            // Played as media, never recording (receive only); used only when
            // a camera's sound is asked for (unmuted)
            val audio = JavaAudioDeviceModule.builder(context.applicationContext)
                .setUseStereoOutput(false)
                .setAudioAttributes(
                    android.media.AudioAttributes.Builder()
                        .setUsage(android.media.AudioAttributes.USAGE_MEDIA)
                        .setContentType(android.media.AudioAttributes.CONTENT_TYPE_MOVIE)
                        .build(),
                )
                .createAudioDeviceModule()
            PeerConnectionFactory.builder()
                .setAudioDeviceModule(audio)
                // The TV's hardware decoders first (H.264 from go2rtc), software after
                .setVideoDecoderFactory(DefaultVideoDecoderFactory(egl.eglBaseContext))
                .setVideoEncoderFactory(DefaultVideoEncoderFactory(egl.eglBaseContext, true, true))
                .createPeerConnectionFactory()
                .also { factory = it }
        }
    }

    companion object {
        private const val TAG = "TvBridge"
        const val START_TIMEOUT_MS = 4000L
    }
}

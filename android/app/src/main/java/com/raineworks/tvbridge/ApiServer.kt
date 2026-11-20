package com.raineworks.tvbridge

import android.content.Context
import android.os.Build
import android.util.Log
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * The local API Home Assistant talks to (protocol/README.md). Everything but
 * /api/info and pairing needs "Authorization: Bearer <token>".
 */
class ApiServer(private val context: Context, port: Int) : NanoHTTPD(port) {

    private val prefs = Prefs(context)

    private class LengthRequired : RuntimeException()

    override fun serve(session: IHTTPSession): Response = try {
        route(session)
    } catch (e: LengthRequired) {
        error(Response.Status.LENGTH_REQUIRED, "Send the body with a Content-Length")
    } catch (e: IllegalArgumentException) {
        error(Response.Status.BAD_REQUEST, e.message ?: "Bad request")
    } catch (e: JSONException) {
        error(Response.Status.BAD_REQUEST, "Invalid JSON: ${e.message}")
    } catch (e: Exception) {
        Log.e(TAG, "Request to ${session.uri} failed", e)
        error(Response.Status.INTERNAL_ERROR, e.toString())
    }

    private fun route(session: IHTTPSession): Response {
        val method = session.method
        val path = session.uri.trimEnd('/')
        // Open: who this is, and pairing
        when {
            method == Method.GET && path == "/api/info" -> return json(info())
            method == Method.POST && path == "/api/pair/start" -> {
                if (Pairing.locked()) return error(Response.Status.TOO_MANY_REQUESTS, "Too many wrong codes: try again later")
                if (!Pairing.mayStart()) return error(Response.Status.TOO_MANY_REQUESTS, "One pairing a second")
                val body = body(session)
                val via = body.optString("via", Pairing.VIA_SCREEN)
                require(via in setOf(Pairing.VIA_SCREEN, Pairing.VIA_ADB, Pairing.VIA_CONFIRM)) {
                    "via must be screen, adb or confirm"
                }
                if (via == Pairing.VIA_CONFIRM) {
                    val name = body.optString("name", "Home Assistant").ifBlank { "Home Assistant" }
                    val address = session.remoteIpAddress ?: "?"
                    return json(JSONObject().put("pairing_id", Pairing.startConfirm(context, name, address)))
                }
                return json(JSONObject().put("pairing_id", Pairing.start(context, via)))
            }
            method == Method.POST && path == "/api/pair/status" ->
                return json(Pairing.status(context, body(session).getString("pairing_id")))
            method == Method.POST && path == "/api/pair/finish" -> {
                val body = body(session)
                val token = Pairing.finish(
                    context, body.getString("pairing_id"), body.getString("code"),
                ) ?: return error(Response.Status.FORBIDDEN, "Wrong or expired code")
                return json(JSONObject().put("token", token))
            }
        }
        val token = session.headers["authorization"]?.removePrefix("Bearer ")?.trim()
        if (!prefs.isPaired(token)) return error(Response.Status.UNAUTHORIZED, "Not paired")
        return when {
            method == Method.GET && path == "/api/state" -> json(state())
            method == Method.GET && path == "/api/diagnostics" -> json(Device.diagnostics(context))
            method == Method.POST && path == "/api/key" -> {
                val key = body(session).getString("key").uppercase().removePrefix("KEYCODE_")
                if (Device.key(context, key)) ok() else error(Response.Status.CONFLICT, "$key needs ADB (network debugging)")
            }
            method == Method.POST && path == "/api/volume" -> {
                Device.setVolume(context, body(session).getDouble("level"))
                ok()
            }
            method == Method.POST && path == "/api/launch" -> {
                if (!TvInfo.overlayAllowed(context)) return overlayNeeded()
                val pkg = body(session).getString("package")
                require(Regex("^[A-Za-z0-9_.]+$").matches(pkg)) { "Not a package: $pkg" }
                if (Device.launch(context, pkg)) ok() else error(Response.Status.NOT_FOUND, "No app $pkg")
            }
            method == Method.POST && path == "/api/open_url" -> {
                if (!TvInfo.overlayAllowed(context)) return overlayNeeded()
                val url = body(session).getString("url")
                require(Regex("^[A-Za-z][A-Za-z0-9+.-]*://\\S+$").matches(url)) { "Not a link: $url" }
                if (Device.openUrl(context, url)) ok() else error(Response.Status.NOT_FOUND, "No app opens $url")
            }
            method == Method.POST && path == "/api/input" -> {
                if (!TvInfo.overlayAllowed(context)) return overlayNeeded()
                if (Device.selectInput(context, body(session).getString("id"))) ok()
                else error(Response.Status.NOT_FOUND, "The TV has no input app")
            }
            method == Method.POST && path == "/api/client" -> {
                // Home Assistant says who it is and how it's connected, for the app's screen
                val body = body(session)
                prefs.clientVersion = body.optString("integration_version", "").take(20)
                prefs.clientAdb = body.optBoolean("adb", false)
                ok()
            }
            method == Method.GET && path == "/api/events" ->
                newChunkedResponse(Response.Status.OK, "application/x-ndjson", Events.open())
            method == Method.GET && path == "/api/apps" -> json(JSONObject().put("apps", apps()))
            method == Method.GET && path == "/api/inputs" -> json(JSONObject().put("inputs", inputs()))
            method == Method.GET && path == "/api/rules" -> json(prefs.rules())
            method == Method.POST && path == "/api/rules" -> {
                val body = body(session)
                body.optJSONArray("hidden_apps")?.let { prefs.hiddenApps = strings(it) }
                body.optJSONArray("blocked_apps")?.let { prefs.blockedApps = strings(it) }
                body.optJSONArray("blocked_inputs")?.let { prefs.blockedInputs = strings(it) }
                if (body.has("default_size")) {
                    val value = body.getString("default_size")
                    require(value in NotificationRequest.SIZES) { "default_size must be one of ${NotificationRequest.SIZES}" }
                    prefs.defaultSize = value
                }
                if (body.has("default_position")) {
                    val value = body.getString("default_position")
                    require(value in NotificationRequest.POSITIONS) { "default_position must be one of ${NotificationRequest.POSITIONS}" }
                    prefs.defaultPosition = value
                }
                if (body.has("when_blocked")) {
                    val value = body.getString("when_blocked")
                    require(value == Prefs.WHEN_BLOCKED_PANEL || value == Prefs.WHEN_BLOCKED_DROP) {
                        "when_blocked must be panel or drop"
                    }
                    prefs.whenBlocked = value
                }
                // Every Home Assistant connected hears of it (more than one may be)
                Events.emit("rules", prefs.rules())
                json(prefs.rules())
            }
            method == Method.POST && path == "/api/notify" -> {
                val request = NotificationRequest.parse(
                    body(session), prefs.defaultPosition, prefs.defaultSize,
                )
                json(Notifier.handle(context, request).toJson().put("instance", Notifier.instance))
            }
            method == Method.POST && path == "/api/dismiss" -> {
                val tag = body(session).optString("tag", "").ifEmpty { null }
                Notifier.dismiss(context, tag)
                json(JSONObject().put("ok", true))
            }
            method == Method.POST && path == "/api/play" -> {
                val request = PlayRequest.parse(body(session))
                // Android lets the app open over what's on only with it
                if (!request.announce && !TvInfo.overlayAllowed(context)) return overlayNeeded()
                if (request.announce) Announcer.announce(context, request) else PlayerActivity.start(context, request)
                json(JSONObject().put("ok", true))
            }
            method == Method.POST && path == "/api/dashboard" -> {
                if (!TvInfo.overlayAllowed(context)) return overlayNeeded()
                val body = body(session)
                val url = body.getString("url")
                require(Regex("^https?://\\S+$", RegexOption.IGNORE_CASE).matches(url)) { "url must be an http(s) URL" }
                DashboardActivity.start(context, url, body.getString("token"))
                json(JSONObject().put("ok", true))
            }
            method == Method.POST && path == "/api/stop" -> {
                PlayerActivity.stop()
                DashboardActivity.stop()
                Announcer.stop(context)
                json(JSONObject().put("ok", true))
            }
            method == Method.POST && path == "/api/unpair" -> {
                prefs.forget(token!!)
                json(JSONObject().put("ok", true))
            }
            else -> error(Response.Status.NOT_FOUND, "No such endpoint: $method $path")
        }
    }

    private fun info(): JSONObject = JSONObject()
        .put("api", API_VERSION)
        .put("app_version", BuildConfig.VERSION_NAME)
        .put("name", TvInfo.deviceName(context))
        .put("manufacturer", Build.MANUFACTURER)
        .put("model", Build.MODEL)
        .put("android", Build.VERSION.RELEASE)
        .put("paired", prefs.tokens.isNotEmpty())
        .put("build", BuildConfig.GIT_SHA)
        // The TV's id (Android ID, as its mDNS announcement says): Home Assistant's unique id for it
        .put("id", android.provider.Settings.Secure.getString(context.contentResolver, android.provider.Settings.Secure.ANDROID_ID))
        // What this app can do, for an integration that knows older ones
        .put("features", org.json.JSONArray(FEATURES))
        // Who installed it: Google Play updates its own; Home Assistant, over ADB, the rest
        .put("installer", installer() ?: JSONObject.NULL)

    private fun installer(): String? = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            context.packageManager.getInstallSourceInfo(context.packageName).installingPackageName
        } else {
            @Suppress("DEPRECATION")
            context.packageManager.getInstallerPackageName(context.packageName)
        }
    } catch (e: Exception) {
        null
    }

    private fun state(): JSONObject = Device.state(context)
        .put("instance", Notifier.instance)
        .put("popups", JSONArray(Overlay.get(context).tags))

    private fun apps(): JSONArray = JSONArray().apply {
        TvInfo.apps(context).forEach {
            put(JSONObject().put("package", it.packageName).put("activity", it.activity).put("name", it.name))
        }
    }

    private fun inputs(): JSONArray = JSONArray().apply {
        TvInfo.inputs(context).forEach { put(JSONObject().put("id", it.id).put("name", it.name)) }
    }

    /** The request's JSON body (UTF-8, at most 64 KB). */
    private fun body(session: IHTTPSession): JSONObject {
        if (session.headers["content-length"] == null && session.headers["transfer-encoding"] != null) {
            throw LengthRequired()
        }
        val length = session.headers["content-length"]?.toIntOrNull() ?: 0
        require(length in 0..MAX_BODY) { "Body too large" }
        if (length == 0) return JSONObject()
        val bytes = ByteArray(length)
        var read = 0
        while (read < length) {
            val n = session.inputStream.read(bytes, read, length - read)
            if (n < 0) break
            read += n
        }
        return JSONObject(String(bytes, 0, read, Charsets.UTF_8))
    }

    private fun strings(array: JSONArray): Set<String> =
        (0 until array.length()).map { array.getString(it) }.filter { it.isNotBlank() }.toSet()

    private fun json(body: JSONObject, status: Response.Status = Response.Status.OK): Response =
        newFixedLengthResponse(status, "application/json; charset=utf-8", body.toString())

    private fun ok(): Response = json(JSONObject().put("ok", true))

    private fun overlayNeeded(): Response =
        error(Response.Status.CONFLICT, "The TV app needs Pop-ups over other apps allowed to open media and dashboards")

    private fun error(status: Response.Status, message: String): Response =
        json(JSONObject().put("error", message), status)

    companion object {
        const val API_VERSION = 1
        val FEATURES = listOf("events", "confirm_pairing", "device", "hidden_apps")
        const val PORT = 8721
        private const val MAX_BODY = 64 * 1024
        private const val TAG = "TvBridge"
    }
}

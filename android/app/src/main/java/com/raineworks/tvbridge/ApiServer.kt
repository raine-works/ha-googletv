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

    override fun serve(session: IHTTPSession): Response = try {
        route(session)
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
                val body = body(session)
                val via = body.optString("via", Pairing.VIA_SCREEN)
                require(via == Pairing.VIA_SCREEN || via == Pairing.VIA_ADB) { "via must be screen or adb" }
                return json(JSONObject().put("pairing_id", Pairing.start(context, via)))
            }
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
            method == Method.GET && path == "/api/apps" -> json(JSONObject().put("apps", apps()))
            method == Method.GET && path == "/api/inputs" -> json(JSONObject().put("inputs", inputs()))
            method == Method.GET && path == "/api/rules" -> json(rules())
            method == Method.POST && path == "/api/rules" -> {
                val body = body(session)
                body.optJSONArray("blocked_apps")?.let { prefs.blockedApps = strings(it) }
                body.optJSONArray("blocked_inputs")?.let { prefs.blockedInputs = strings(it) }
                if (body.has("when_blocked")) {
                    val value = body.getString("when_blocked")
                    require(value == Prefs.WHEN_BLOCKED_PANEL || value == Prefs.WHEN_BLOCKED_DROP) {
                        "when_blocked must be panel or drop"
                    }
                    prefs.whenBlocked = value
                }
                json(rules())
            }
            method == Method.POST && path == "/api/notify" -> {
                val request = NotificationRequest.parse(body(session))
                json(Notifier.handle(context, request).toJson())
            }
            method == Method.POST && path == "/api/dismiss" -> {
                val tag = body(session).optString("tag", "")
                if (tag.isEmpty()) Overlay.get(context).dismissAll() else Overlay.get(context).dismiss(tag)
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

    private fun state(): JSONObject = JSONObject()
        .put("screen_on", TvInfo.screenOn(context))
        .put("foreground_app", TvInfo.foregroundApp(context) ?: JSONObject.NULL)
        .put("overlay_permission", TvInfo.overlayAllowed(context))
        .put("usage_access", TvInfo.usageAccess(context))

    private fun apps(): JSONArray = JSONArray().apply {
        TvInfo.apps(context).forEach {
            put(JSONObject().put("package", it.packageName).put("name", it.name))
        }
    }

    private fun inputs(): JSONArray = JSONArray().apply {
        TvInfo.inputs(context).forEach { put(JSONObject().put("id", it.id).put("name", it.name)) }
    }

    private fun rules(): JSONObject = JSONObject()
        .put("blocked_apps", JSONArray(prefs.blockedApps.sorted()))
        .put("blocked_inputs", JSONArray(prefs.blockedInputs.sorted()))
        .put("when_blocked", prefs.whenBlocked)

    /** The request's JSON body (UTF-8, at most 64 KB). */
    private fun body(session: IHTTPSession): JSONObject {
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

    private fun error(status: Response.Status, message: String): Response =
        json(JSONObject().put("error", message), status)

    companion object {
        const val API_VERSION = 1
        const val PORT = 8721
        private const val MAX_BODY = 64 * 1024
        private const val TAG = "TvBridge"
    }
}

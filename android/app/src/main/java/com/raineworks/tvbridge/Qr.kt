package com.raineworks.tvbridge

import android.graphics.Bitmap
import android.graphics.Color
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel

/** QR codes for the setup screen: dark modules on white, as phones read best. */
object Qr {
    /** Where the QR code leads: the integration in the Home Assistant Marketplace, in your own Home Assistant. */
    const val MARKETPLACE_URL =
        "https://my.home-assistant.io/redirect/marketplace_repository/?owner=raine-works&repository=ha-googletv&category=integration"

    /** Adding a TV in your Home Assistant, once the integration is in: it asks for this TV's address. */
    const val ADD_TV_URL = "https://my.home-assistant.io/redirect/config_flow_start/?domain=googletv"

    fun bitmap(text: String, sizePx: Int): Bitmap {
        val matrix = QRCodeWriter().encode(
            text,
            BarcodeFormat.QR_CODE,
            sizePx,
            sizePx,
            mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 0),
        )
        val pixels = IntArray(matrix.width * matrix.height) { i ->
            if (matrix.get(i % matrix.width, i / matrix.width)) Color.BLACK else Color.WHITE
        }
        return Bitmap.createBitmap(pixels, matrix.width, matrix.height, Bitmap.Config.ARGB_8888)
    }
}

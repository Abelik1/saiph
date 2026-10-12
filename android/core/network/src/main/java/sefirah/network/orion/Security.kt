package sefirah.network.orion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.Signature
import java.util.UUID

object Security {
    private const val ALIAS = "orion_device_p256"
    fun ensureKey() {
        val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
        if (ks.containsAlias(ALIAS)) return
        val gen=KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC,"AndroidKeyStore")
        gen.initialize(KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
            .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256).build())
        gen.generateKeyPair()
    }
    fun publicKeyB64():String { ensureKey(); val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}; return Base64.encodeToString(ks.getCertificate(ALIAS).publicKey.encoded,Base64.NO_WRAP) }
    fun signedHeaders(context:Context, method:String, pathQs:String, body:ByteArray):Map<String,String>{
        ensureKey(); val prefs=context.getSharedPreferences("orion",Context.MODE_PRIVATE); val device=prefs.getString("device_id","")?:""
        val ts=(System.currentTimeMillis()/1000).toString(); val nonce=UUID.randomUUID().toString(); val digest=MessageDigest.getInstance("SHA-256").digest(body).joinToString(""){"%02x".format(it)}
        val canonical="${method.uppercase()}\n$pathQs\n$ts\n$nonce\n$digest".toByteArray()
        val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}; val sig=Signature.getInstance("SHA256withECDSA"); sig.initSign(ks.getKey(ALIAS,null) as java.security.PrivateKey); sig.update(canonical)
        return mapOf("X-Orion-Device-Id" to device,"X-Orion-Timestamp" to ts,"X-Orion-Nonce" to nonce,"X-Orion-Signature" to Base64.encodeToString(sig.sign(),Base64.NO_WRAP))
    }
}

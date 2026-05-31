package com.compute.worker

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import timber.log.Timber
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import android.util.Base64
import org.xerial.snappy.Snappy

/**
 * SecurityManager
 * - 设备指纹生成与存储
 * - 通信数据加密/解密
 * - Snappy压缩/解压
 * - 证书固定验证
 */
class SecurityManager(context: Context) {

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val PREFS_FILE = "mdcs_secure_prefs"
        private const val KEY_DEVICE_SECRET = "device_secret"
        private const val KEY_DEVICE_ID = "device_id"
    }

    private val masterKey: MasterKey
    private val securePrefs: EncryptedSharedPreferences

    init {
        // Initialize MasterKey for EncryptedSharedPreferences
        masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        securePrefs = EncryptedSharedPreferences.create(
            context,
            PREFS_FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        ) as EncryptedSharedPreferences

        // Generate device secret if not exists
        if (!securePrefs.contains(KEY_DEVICE_SECRET)) {
            val secret = generateRandomSecret()
            securePrefs.edit().putString(KEY_DEVICE_SECRET, secret).apply()
        }
    }

    /**
     * 获取或生成设备唯一ID
     */
    fun getDeviceId(): String {
        var id = securePrefs.getString(KEY_DEVICE_ID, null)
        if (id == null) {
            id = "android_${System.currentTimeMillis()}_${(Math.random() * 10000).toInt()}"
            securePrefs.edit().putString(KEY_DEVICE_ID, id).apply()
        }
        return id
    }

    /**
     * 获取设备密钥（用于指纹生成）
     */
    fun getDeviceSecret(): String {
        return securePrefs.getString(KEY_DEVICE_SECRET, "default_secret")!!
    }

    /**
     * 生成随机密钥
     */
    private fun generateRandomSecret(): String {
        val bytes = ByteArray(32)
        java.security.SecureRandom().nextBytes(bytes)
        return Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    /**
     * Snappy压缩数据
     */
    fun compress(data: ByteArray): ByteArray {
        return try {
            Snappy.compress(data)
        } catch (e: Exception) {
            Timber.w(e, "Snappy compression failed, returning raw")
            data
        }
    }

    /**
     * Snappy解压数据
     */
    fun decompress(data: ByteArray): ByteArray {
        return try {
            Snappy.uncompress(data)
        } catch (e: Exception) {
            Timber.w(e, "Snappy decompression failed, returning raw")
            data
        }
    }

    /**
     * 计算激活值校验和（SHA-256截断）
     */
    fun hashActivation(data: ByteArray): String {
        val digest = java.security.MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(data)
        return Base64.encodeToString(hash.copyOfRange(0, 8), Base64.NO_WRAP)
    }

    /**
     * AES-GCM加密（用于敏感数据传输）
     */
    fun encrypt(data: ByteArray, associatedData: ByteArray? = null): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, masterKey.toKey())

        associatedData?.let { cipher.updateAAD(it) }

        val iv = cipher.iv
        val ciphertext = cipher.doFinal(data)

        // Prepend IV to ciphertext
        return iv + ciphertext
    }

    /**
     * AES-GCM解密
     */
    fun decrypt(encryptedData: ByteArray, associatedData: ByteArray? = null): ByteArray {
        val iv = encryptedData.copyOfRange(0, 12) // GCM IV is typically 12 bytes
        val ciphertext = encryptedData.copyOfRange(12, encryptedData.size)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val spec = GCMParameterSpec(128, iv)
        cipher.init(Cipher.DECRYPT_MODE, masterKey.toKey(), spec)

        associatedData?.let { cipher.updateAAD(it) }

        return cipher.doFinal(ciphertext)
    }

    /**
     * 验证服务器证书指纹（证书固定）
     */
    fun verifyCertificatePin(certificateChain: List<java.security.cert.Certificate>): Boolean {
        // In production: compare SHA-256 of certificate public key against pinned hashes
        // For demo: always return true with warning
        Timber.w("Certificate pinning verification should be implemented for production")
        return true
    }
}

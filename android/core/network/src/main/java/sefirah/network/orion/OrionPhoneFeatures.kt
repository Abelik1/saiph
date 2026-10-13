package sefirah.network.orion

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.telecom.TelecomManager
import android.telephony.TelephonyManager
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import sefirah.communication.sms.SmsFeature
import sefirah.communication.sms.SMSHelper
import sefirah.communication.call.CallStateFeature
import sefirah.communication.call.CallLogHelper
import sefirah.communication.utils.ContactsHelper
import sefirah.media.PlaybackFeature
import sefirah.status.DeviceControlHandler
import android.net.Uri
import android.os.Bundle
import sefirah.domain.model.*
import sefirah.common.util.smsPermissionGranted
import sefirah.common.util.phoneStatePermissionGranted
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/** Retained upstream features; the phone resolves recipients and executes actions. */
@Singleton
class OrionPhoneFeatures @Inject constructor(private val context: Context,
    private val sms: SmsFeature, private val calls: CallStateFeature,
    private val direct: OrionDirectFiles, private val link: OrionLink,
    private val playback: PlaybackFeature, private val controls: DeviceControlHandler) {
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private val receipts=CommandReceipts(context)
    private var smsEnabled=false
    private var callsEnabled=false
    private var mediaEnabled=false
    private var contactCache: Pair<Long,List<ContactInfo>>? = null
    private val refreshMutex=Mutex()
    suspend fun refresh() = refreshMutex.withLock { refreshLocked(syncMessages=true) }
    suspend fun refreshPermissions() = refreshMutex.withLock { refreshLocked(syncMessages=link.status.value=="Online",refreshPhotos=false) }
    private suspend fun refreshLocked(syncMessages: Boolean, refreshPhotos: Boolean = true) {
        val messages=smsPermissionGranted(context)
        if(messages && !smsEnabled) { link.invalidateConversations();sms.enable("");smsEnabled=true;if(syncMessages)sms.handleConversationsRequest("",ConversationsRequest(link.knownConversations())) }
        if(!messages && smsEnabled) { sms.disable("");smsEnabled=false }
        val call=phoneStatePermissionGranted(context)
        if(call && !callsEnabled) { calls.enable("");callsEnabled=true }
        if(!call && callsEnabled) { calls.disable("");callsEnabled=false }
        if(refreshPhotos) direct.refreshPhotos() else direct.refreshPhotoAccess()
        // Media sessions are read through notification access, like upstream.
        val notifications=OrionPermissions.read(context).notifications
        if(notifications && !mediaEnabled) { playback.enable("");mediaEnabled=true }
        if(!notifications && mediaEnabled) { playback.disable("");mediaEnabled=false;media.retain(emptySet()) }
        if(mediaEnabled) media.retain(playback.getActivePackageNames())?.let { link.publish("media.state",it) }
    }
    suspend fun connected() = refreshMutex.withLock {
        refreshLocked(syncMessages=false);if(smsEnabled)sms.handleConversationsRequest("",ConversationsRequest(link.knownConversations()))
        if(mediaEnabled) link.publish("media.state",media.state())
    }
    suspend fun stop() = refreshMutex.withLock { if(smsEnabled)sms.disable("");if(callsEnabled)calls.disable("");if(mediaEnabled)playback.disable("");smsEnabled=false;callsEnabled=false;mediaEnabled=false;direct.stop() }
    fun receive(event: JsonObject) {
        val kind=event.getValue("type").jsonPrimitive.content
        val body=event.getValue("payload").jsonObject
        val id=event.getValue("id").jsonPrimitive.content
        when(kind) {
            "sms.open" -> if(smsPermissionGranted(context)) sms.handleMessagesRequest("",MessagesRequest(body.getValue("thread").jsonPrimitive.long))
            "sms.send" -> if(smsPermissionGranted(context) && receipts.claim(id)) {
                val thread=body.getValue("thread").jsonPrimitive.long
                val recipients=SMSHelper.getThreadRecipients(context,thread).take(10)
                val text=body.getValue("text").jsonPrimitive.content
                require(recipients.size==1 && text.isNotBlank() && text.length<=4096)
                val subscription=SMSHelper.getNewestMessageRef(context,thread)?.let { SMSHelper.getMessagesByRefs(context,listOf(it)).firstOrNull()?.subscriptionID } ?: 0
                sms.sendTextMessage("",TextMessage(uniqueId=(UUID.fromString(id).leastSignificantBits and Long.MAX_VALUE),addresses=recipients,body=text,subscriptionId=subscription))
            }
            "call.command" -> if(phoneStatePermissionGranted(context) && hasPermission(context,Manifest.permission.ANSWER_PHONE_CALLS) && receipts.claim(id)) {
                @Suppress("DEPRECATION")
                val telecom=context.getSystemService(TelecomManager::class.java)
                @Suppress("DEPRECATION")
                when(body.getValue("operation").jsonPrimitive.content) {
                    "answer" -> if(context.getSystemService(TelephonyManager::class.java).callState==TelephonyManager.CALL_STATE_RINGING)telecom.acceptRingingCall()
                    "reject" -> if(context.getSystemService(TelephonyManager::class.java).callState==TelephonyManager.CALL_STATE_RINGING)telecom.endCall()
                }
            }
            "sms.compose" -> if(smsPermissionGranted(context) && receipts.claim(id)) {
                // A new conversation: one recipient chosen on the computer.
                val addresses=body.getValue("addresses").jsonArray.map { it.jsonPrimitive.content }
                val text=body.getValue("text").jsonPrimitive.content
                require(addresses.size==1 && addresses.all { it.isNotBlank() && it.length<=120 } && text.isNotBlank() && text.length<=4096)
                sms.sendTextMessage("",TextMessage(uniqueId=(UUID.fromString(id).leastSignificantBits and Long.MAX_VALUE),addresses=addresses,body=text))
            }
            "contacts.search" -> if(hasPermission(context,Manifest.permission.READ_CONTACTS)) {
                val cached=contactCache?.takeIf { System.currentTimeMillis()-it.first<60_000 }?.second
                val all=cached ?: ContactsHelper().getAllContacts(context).also { contactCache=System.currentTimeMillis() to it }
                link.publish("contacts.results",PhoneFeatureFrames.contacts(body.getValue("query").jsonPrimitive.content.take(64),all),event.getValue("source").jsonPrimitive.content)
            }
            "calls.log.request" -> if(hasPermission(context,Manifest.permission.READ_CALL_LOG))
                link.publish("calls.log",PhoneFeatureFrames.callLog(CallLogHelper.getCallLogs(context)),event.getValue("source").jsonPrimitive.content)
            "call.dial" -> if(hasPermission(context,Manifest.permission.CALL_PHONE) && receipts.claim(id)) {
                val number=body.getValue("number").jsonPrimitive.content
                require(PhoneFeatureFrames.dialable(number))
                // Telecom shows the in-call screen; audio stays on the phone.
                context.getSystemService(TelecomManager::class.java).placeCall(Uri.fromParts("tel",number,null),Bundle())
            }
            "phone.ringer" -> if(context.getSystemService(android.app.NotificationManager::class.java).isNotificationPolicyAccessGranted && receipts.claim(id))
                controls.handleRingerMode(RingerModeState(PhoneFeatureFrames.ringerMode(body.getValue("mode").jsonPrimitive.content)))
            "media.command" -> if(mediaEnabled && receipts.claim(id)) {
                val type=when(body.getValue("action").jsonPrimitive.content) { "play"->MediaActionType.Play; "pause"->MediaActionType.Pause; "next"->MediaActionType.Next
                    "previous"->MediaActionType.Previous; "seek"->MediaActionType.Seek; "volume"->MediaActionType.VolumeUpdate; else->throw IllegalArgumentException() }
                val action=MediaAction(type,body.getValue("source").jsonPrimitive.content,body["value"]?.jsonPrimitive?.longOrNull?.toDouble())
                scope.launch { playback.handlePlaybackAction("",action) }
            }
            "sms.attachment.request" -> if(smsPermissionGranted(context))
                direct.sendMmsPart(body.getValue("thread").jsonPrimitive.long,body.getValue("message").jsonPrimitive.long,body.getValue("part").jsonPrimitive.long,event.getValue("source").jsonPrimitive.content)
            "photo.request" -> direct.sendOriginal(body.getValue("id").jsonPrimitive.content,event.getValue("source").jsonPrimitive.content)
            "file.offer" -> direct.enqueue(event)
        }
    }
    companion object {
        val media=OrionMedia()
        fun hasPermission(context: Context,permission: String)=context.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED
        fun capabilities(context: Context): List<String> = OrionPermissions.read(context).capabilities()
        fun send(link: OrionLink,target: String?,value: SocketMessage): Boolean? {
            val frames=PhoneFeatureFrames.encode(value) ?: return null
            return frames.all { (type,payload)->link.publish(type,payload,target,(value as? ConversationInfo)?.checksum) }
        }
    }
}

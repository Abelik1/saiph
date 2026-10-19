// SPDX-License-Identifier: AGPL-3.0-or-later
package ie.orion.acceptance.pad;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.net.Uri;
import android.os.*;
import android.provider.MediaStore;
import android.widget.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Disposable offline native endpoints. Never operates the owner's other apps/data. */
public class Pad extends Activity {
    static volatile Pad current;
    static final String AUTHORITY = "ie.orion.acceptance.pad.fixtures";
    static final String NOTICE = "ORION-ACCEPTANCE-NOTICE";
    EditText editor;
    static android.content.SharedPreferences prefs(Context c) { return c.getSharedPreferences("fixture", 0); }
    static String hash(byte[] data) throws Exception {
        StringBuilder out = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(data)) out.append(String.format("%02x", b & 255));
        return out.toString();
    }
    static Bitmap image() {
        Bitmap b = Bitmap.createBitmap(240,160,Bitmap.Config.ARGB_8888);
        for(int y=0;y<160;y++) for(int x=0;x<240;x++) b.setPixel(x,y,((x/20+y/20)%2==1)?0xff26b6cb:0xff293541);
        return b;
    }
    static boolean matches(Bitmap b) {
        if(b==null || b.getWidth()!=240 || b.getHeight()!=160) return false;
        for(int y=0;y<160;y++) for(int x=0;x<240;x++) {
            int expected=((x/20+y/20)%2==1)?0xff26b6cb:0xff293541;
            if(b.getPixel(x,y)!=expected)return false;
        }
        return true;
    }
    static Bitmap alphaImage() {
        Bitmap b=Bitmap.createBitmap(240,160,Bitmap.Config.ARGB_8888);
        for(int y=0;y<160;y++)for(int x=0;x<240;x++) {
            int alpha=(x/80)*127; if(x>=160)alpha=255;
            b.setPixel(x,y,Color.argb(alpha,40,180,(y/20)%2==0?200:80));
        }
        return b;
    }
    static boolean matchesAlpha(Bitmap b) {
        if(b==null||b.getWidth()!=240||b.getHeight()!=160)return false;
        Bitmap expected=alphaImage();boolean match=true;
        for(int y=0;y<160&&match;y++)for(int x=0;x<240;x++) {
            int a=b.getPixel(x,y),e=expected.getPixel(x,y);
            if(Color.alpha(a)!=Color.alpha(e)||Color.alpha(e)>0&&(Math.abs(Color.red(a)-Color.red(e))>1||Math.abs(Color.green(a)-Color.green(e))>1||Math.abs(Color.blue(a)-Color.blue(e))>1)){match=false;break;}
        }
        expected.recycle();return match;
    }
    static File file(Context c,String name) throws Exception {
        if(name==null || !name.startsWith("ORION-") || name.length()>180 || name.chars().anyMatch(ch -> ch<32 || "/\\:*?\"<>|#".indexOf(ch)>=0)) throw new IllegalArgumentException("Fixture filename required");
        return new File(c.getFilesDir(),name);
    }
    static File makeFile(Context c,String name) throws Exception {
        File f=file(c,name);
        try(FileOutputStream out=new FileOutputStream(f)) {
            if(name.endsWith(".empty.txt")) { /* Deliberately zero bytes. */ }
            else if(name.endsWith(".malformed.png"))out.write("ORION deliberately invalid synthetic image".getBytes(StandardCharsets.US_ASCII));
            else if(name.endsWith(".alpha.png")) { Bitmap b=alphaImage();b.compress(Bitmap.CompressFormat.PNG,100,out);b.recycle(); }
            else if(name.endsWith(".webp")) { Bitmap b=image();b.compress(Bitmap.CompressFormat.WEBP_LOSSLESS,100,out);b.recycle(); }
            else if(name.endsWith(".jpg")) { Bitmap b=image();b.compress(Bitmap.CompressFormat.JPEG,95,out);b.recycle(); }
            else if(name.endsWith(".png")) { Bitmap b=image(); b.compress(Bitmap.CompressFormat.PNG,100,out);b.recycle(); }
            else out.write("Orion phone to laptop acceptance fixture\nSynthetic content only.\n".getBytes(StandardCharsets.UTF_8));
        }
        if(name.endsWith(".rotated.jpg")) {
            android.media.ExifInterface exif=new android.media.ExifInterface(f.getAbsolutePath());
            exif.setAttribute(android.media.ExifInterface.TAG_ORIENTATION,String.valueOf(android.media.ExifInterface.ORIENTATION_ROTATE_90));exif.saveAttributes();
        }
        prefs(c).edit().putString("fixture_name",name).putString("fixture_sha256",hash(java.nio.file.Files.readAllBytes(f.toPath()))).apply();
        return f;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // Only this visible disposable endpoint stays awake during a fixture
        // round. This never unlocks the device or changes its lock settings.
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        current=this;
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setPadding(25,25,25,25);
        TextView title=new TextView(this);title.setText("Saiph Acceptance Pad — synthetic tests");layout.addView(title);
        editor=new EditText(this);editor.setMinLines(5);layout.addView(editor);
        setContentView(layout);
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
        editor.requestFocus();
        new Handler(Looper.getMainLooper()).postDelayed(() -> perform(getIntent()),500);
    }
    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i);setIntent(i);new Handler(Looper.getMainLooper()).postDelayed(() -> perform(i),300); }
    void perform(Intent i) {
        String action=i.getStringExtra("command"); if(action==null)return;
        prefs(this).edit().remove("error").putString("last_action",action).apply();
        try {
            ClipboardManager clip=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
            String value=i.getStringExtra("value");
            switch(action) {
                case "copy_text":
                    if(value==null || !value.startsWith("ORION-") || value.length()>20000)throw new IllegalArgumentException("Synthetic text required");
                    editor.setText(value);editor.selectAll();editor.onTextContextMenuItem(android.R.id.copy);break;
                case "clear_clipboard":clip.clearPrimaryClip();break;
                case "paste_text":
                    editor.setText("");editor.onTextContextMenuItem(android.R.id.paste);
                    prefs(this).edit().putString("text_sha256",hash(editor.getText().toString().getBytes(StandardCharsets.UTF_8))).putBoolean("text_match",editor.getText().toString().equals(value)).apply();break;
                case "copy_image": {
                    String variant=i.getStringExtra("variant");if(variant==null)variant="checker";
                    String suffix;
                    switch(variant){case "checker":suffix=".png";break;case "alpha":suffix=".alpha.png";break;case "webp":suffix=".webp";break;case "rotated_jpeg":suffix=".rotated.jpg";break;case "malformed":suffix=".malformed.png";break;default:throw new IllegalArgumentException("Known image fixture required");}
                    String name="ORION-PHONE-CLIPBOARD"+suffix;makeFile(this,name);
                    clip.setPrimaryClip(ClipData.newUri(getContentResolver(),"Synthetic checkerboard",Uri.parse("content://"+AUTHORITY+"/"+name)));break;
                }
                case "paste_image": {
                    ClipData data=clip.getPrimaryClip();Bitmap b=null;
                    prefs(this).edit().putBoolean("clipboard_has_uri",data!=null && data.getItemCount()>0 && data.getItemAt(0).getUri()!=null)
                        .putBoolean("clipboard_has_text",data!=null && data.getItemCount()>0 && data.getItemAt(0).getText()!=null)
                        .putString("clipboard_mime",data!=null && data.getDescription().getMimeTypeCount()>0?data.getDescription().getMimeType(0):"none").apply();
                    if(data!=null && data.getItemCount()>0 && data.getItemAt(0).getUri()!=null)
                        try(InputStream in=getContentResolver().openInputStream(data.getItemAt(0).getUri())) { b=BitmapFactory.decodeStream(in); }
                    boolean match="alpha".equals(i.getStringExtra("variant"))?matchesAlpha(b):matches(b);
                    prefs(this).edit().putBoolean("image_match",match).putInt("image_width",b==null?0:b.getWidth()).putInt("image_height",b==null?0:b.getHeight()).apply();
                    if(b!=null) { ImageView view=new ImageView(this);view.setImageBitmap(b);((LinearLayout)editor.getParent()).addView(view); }break;
                }
                case "share_file": {
                    String name=i.getStringExtra("name");makeFile(this,name);Uri uri=Uri.parse("content://"+AUTHORITY+"/"+name);
                    Intent send=new Intent(Intent.ACTION_SEND).setComponent(new ComponentName("com.orionmini.mobile","com.orionmini.mobile.OrionShareActivity"))
                        .setType(name.endsWith(".png")?"image/png":"text/plain").putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    send.setClipData(ClipData.newRawUri("Synthetic fixture",uri));
                    grantUriPermission("com.orionmini.mobile",uri,Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivity(send);break;
                }
                case "notification": {
                    prefs(this).edit().remove("mark_count").remove("reply_count").remove("reply_match").apply();
                    NotificationManager nm=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
                    nm.createNotificationChannel(new NotificationChannel("fixture","Acceptance fixture",NotificationManager.IMPORTANCE_DEFAULT));
                    PendingIntent mark=PendingIntent.getBroadcast(this,1,new Intent(this,FixtureAction.class).setAction("mark"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
                    PendingIntent reply=PendingIntent.getBroadcast(this,2,new Intent(this,FixtureAction.class).setAction("reply"),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_MUTABLE);
                    Notification.Action replyAction=new Notification.Action.Builder(android.R.drawable.ic_dialog_email,"Reply fixture",reply).addRemoteInput(new RemoteInput.Builder("fixture_reply").setLabel("Synthetic reply").build()).build();
                    nm.notify(55,new Notification.Builder(this,"fixture").setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(NOTICE).setContentText("Synthetic laptop-phone acceptance notification")
                        .addAction(new Notification.Action.Builder(android.R.drawable.ic_menu_add,"Mark fixture",mark).build()).addAction(replyAction).build());break;
                }
                case "publish_photo": {
                    String name=i.getStringExtra("name");file(this,name);ContentValues values=new ContentValues();values.put(MediaStore.Images.Media.DISPLAY_NAME,name);values.put(MediaStore.Images.Media.MIME_TYPE,"image/png");values.put(MediaStore.Images.Media.RELATIVE_PATH,"Pictures/OrionAcceptance");
                    Uri uri=getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,values);
                    try(OutputStream out=getContentResolver().openOutputStream(uri)) { Bitmap b=image();b.compress(Bitmap.CompressFormat.PNG,100,out);b.recycle(); }
                    String digest;try(InputStream input=getContentResolver().openInputStream(uri);ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
                        byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1) { bytes.write(buffer,0,count);if(bytes.size()>1048576)throw new IOException("Fixture exceeds expected size"); }
                        digest=hash(bytes.toByteArray());
                    }
                    prefs(this).edit().putString("photo_uri",uri.toString()).putString("photo_name",name).putString("photo_id",uri.getLastPathSegment()).putString("photo_sha256",digest).apply();break;
                }
                case "cleanup": {
                    String uri=prefs(this).getString("photo_uri",null);if(uri!=null)getContentResolver().delete(Uri.parse(uri),null,null);
                    ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).cancelAll();break;
                }
                default: throw new IllegalArgumentException("Unknown fixture command");
            }
        } catch(Exception error) { prefs(this).edit().putString("error",error.getClass().getSimpleName()).apply(); }
        prefs(this).edit().putString("completed_action",action).putLong("completed_at",System.currentTimeMillis()).apply();
    }
}

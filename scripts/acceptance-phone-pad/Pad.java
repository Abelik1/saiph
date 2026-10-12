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
    static File file(Context c,String name) throws Exception {
        if(!name.matches("ORION-[A-Za-z0-9._-]+")) throw new IllegalArgumentException("Fixture filename required");
        return new File(c.getFilesDir(),name);
    }
    static File makeFile(Context c,String name) throws Exception {
        File f=file(c,name);
        try(FileOutputStream out=new FileOutputStream(f)) {
            if(name.endsWith(".png")) { Bitmap b=image(); b.compress(Bitmap.CompressFormat.PNG,100,out);b.recycle(); }
            else out.write("Orion phone to laptop acceptance fixture\nSynthetic content only.\n".getBytes(StandardCharsets.UTF_8));
        }
        prefs(c).edit().putString("fixture_name",name).putString("fixture_sha256",hash(java.nio.file.Files.readAllBytes(f.toPath()))).apply();
        return f;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
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
                    if(value==null || !value.startsWith("ORION-") || value.length()>4096)throw new IllegalArgumentException("Synthetic text required");
                    editor.setText(value);editor.selectAll();editor.onTextContextMenuItem(android.R.id.copy);break;
                case "paste_text":
                    editor.setText("");editor.onTextContextMenuItem(android.R.id.paste);
                    prefs(this).edit().putString("text_sha256",hash(editor.getText().toString().getBytes(StandardCharsets.UTF_8))).putBoolean("text_match",editor.getText().toString().equals(value)).apply();break;
                case "copy_image": {
                    String name="ORION-PHONE-CLIPBOARD.png";makeFile(this,name);
                    clip.setPrimaryClip(ClipData.newUri(getContentResolver(),"Synthetic checkerboard",Uri.parse("content://"+AUTHORITY+"/"+name)));break;
                }
                case "paste_image": {
                    ClipData data=clip.getPrimaryClip();Bitmap b=null;
                    if(data!=null && data.getItemCount()>0 && data.getItemAt(0).getUri()!=null)
                        try(InputStream in=getContentResolver().openInputStream(data.getItemAt(0).getUri())) { b=BitmapFactory.decodeStream(in); }
                    prefs(this).edit().putBoolean("image_match",matches(b)).putInt("image_width",b==null?0:b.getWidth()).putInt("image_height",b==null?0:b.getHeight()).apply();
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
                    String name=i.getStringExtra("name");ContentValues values=new ContentValues();values.put(MediaStore.Images.Media.DISPLAY_NAME,name);values.put(MediaStore.Images.Media.MIME_TYPE,"image/png");values.put(MediaStore.Images.Media.RELATIVE_PATH,"Pictures/OrionAcceptance");
                    Uri uri=getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,values);
                    try(OutputStream out=getContentResolver().openOutputStream(uri)) { Bitmap b=image();b.compress(Bitmap.CompressFormat.PNG,100,out);b.recycle(); }
                    prefs(this).edit().putString("photo_uri",uri.toString()).putString("photo_name",name).putString("photo_id",uri.getLastPathSegment()).apply();break;
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

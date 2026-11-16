package io.github.timboat.desrecomp;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.Looper;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;

import java.util.ArrayList;
import java.util.List;

/**
 * On-screen controls over the game: two floating sticks, the face buttons, the shoulders, a D-pad, START /
 * SELECT and R3 (lock on). Their state goes to the game's pad port 0 through nativeTouchPad
 * (android_main.cpp -> cellPad.c's ps3_pad_touch_set), merged with a real controller or keyboard if one
 * is there too. Hidden while a game controller is connected (it comes back when the last one goes).
 *
 * Layout, in units of a tenth of the screen's height: the left stick appears where a thumb lands in the
 * lower left, the right stick (camera) anywhere on the right half that is not a button.
 */
public class TouchControls extends View implements InputManager.InputDeviceListener {
    static native void nativeTouchPad(int buttons, int sticks);

    // CELL_PAD_CTRL_* (libs/input/cellPad.h)
    static final int SELECT = 1, L3 = 1 << 1, R3 = 1 << 2, START = 1 << 3, UP = 1 << 4, RIGHT = 1 << 5,
            DOWN = 1 << 6, LEFT = 1 << 7, L2 = 1 << 8, R2 = 1 << 9, L1 = 1 << 10, R1 = 1 << 11,
            TRIANGLE = 1 << 12, CIRCLE = 1 << 13, CROSS = 1 << 14, SQUARE = 1 << 15;

    static final class Btn {
        final int mask; final String label; final boolean round;
        RectF r = new RectF();
        int pointer = -1;
        Btn(int mask, String label, boolean round) { this.mask = mask; this.label = label; this.round = round; }
    }

    static final class Stick {
        int pointer = -1;
        float ox, oy, x, y;       // where the thumb landed, where it is now
        float homeX, homeY;       // drawn there while untouched
        int ax = 128, ay = 128;   // 0..255
    }

    private final List<Btn> btns = new ArrayList<>();
    private final Stick ls = new Stick(), rs = new Stick();
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG), line = new Paint(Paint.ANTI_ALIAS_FLAG),
            text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float u = 100;        // a tenth of the height, in pixels
    private float stickR = 120;
    private int sentButtons = 0, sentSticks = 0x80808080;
    private final InputManager im;

    public TouchControls(Context ctx) {
        super(ctx);
        setFocusable(false);      // keys stay with SDL's surface
        setFocusableInTouchMode(false);
        btns.add(new Btn(CROSS, "✕", true));
        btns.add(new Btn(CIRCLE, "○", true));
        btns.add(new Btn(SQUARE, "□", true));
        btns.add(new Btn(TRIANGLE, "△", true));
        btns.add(new Btn(L1, "L1", false));
        btns.add(new Btn(L2, "L2", false));
        btns.add(new Btn(R1, "R1", false));
        btns.add(new Btn(R2, "R2", false));
        btns.add(new Btn(UP, "▲", true));
        btns.add(new Btn(DOWN, "▼", true));
        btns.add(new Btn(LEFT, "◀", true));
        btns.add(new Btn(RIGHT, "▶", true));
        btns.add(new Btn(SELECT, "SELECT", false));
        btns.add(new Btn(START, "START", false));
        btns.add(new Btn(R3, "R3", true));
        line.setStyle(Paint.Style.STROKE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setColor(0xFFFFFFFF);
        im = (InputManager) ctx.getSystemService(Context.INPUT_SERVICE);
        if (im != null) im.registerInputDeviceListener(this, new Handler(Looper.getMainLooper()));
        updateVisibility();
    }

    private void place(int mask, float cx, float cy, float w, float h) {
        for (Btn b : btns) if (b.mask == mask) b.r.set(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2);
    }

    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        u = h / 10f;
        stickR = 1.3f * u;
        float fb = 1.05f * u, fr = 1.1f * u;                       // face buttons: spacing, size
        float fx = w - 2.3f * u, fy = h - 2.6f * u;
        place(TRIANGLE, fx, fy - fb, fr, fr);
        place(CROSS, fx, fy + fb, fr, fr);
        place(SQUARE, fx - fb, fy, fr, fr);
        place(CIRCLE, fx + fb, fy, fr, fr);
        place(R3, fx - 2.4f * u, h - 1.0f * u, 0.9f * u, 0.9f * u);
        float sw = 1.7f * u, sh = 0.85f * u;                       // shoulders
        place(L2, 1.3f * u, 0.75f * u, sw, sh);
        place(L1, 1.3f * u, 1.85f * u, sw, sh);
        place(R2, w - 1.3f * u, 0.75f * u, sw, sh);
        place(R1, w - 1.3f * u, 1.85f * u, sw, sh);
        float dx = 1.9f * u, dy = 4.3f * u, db = 0.8f * u, dr = 0.75f * u;   // D-pad
        place(UP, dx, dy - db, dr, dr);
        place(DOWN, dx, dy + db, dr, dr);
        place(LEFT, dx - db, dy, dr, dr);
        place(RIGHT, dx + db, dy, dr, dr);
        place(SELECT, w / 2f - 1.1f * u, 0.55f * u, 1.7f * u, 0.65f * u);
        place(START, w / 2f + 1.1f * u, 0.55f * u, 1.7f * u, 0.65f * u);
        ls.homeX = 3.4f * u; ls.homeY = h - 2.4f * u;
        rs.homeX = w - 5.6f * u; rs.homeY = h - 4.6f * u;
        text.setTextSize(0.38f * u);
        line.setStrokeWidth(Math.max(2f, 0.04f * u));
    }

    private Btn hit(float x, float y) {
        float slack = 0.15f * u;
        for (Btn b : btns)
            if (x >= b.r.left - slack && x <= b.r.right + slack && y >= b.r.top - slack && y <= b.r.bottom + slack)
                return b;
        return null;
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        final int action = e.getActionMasked();
        final int idx = e.getActionIndex();
        switch (action) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN: {
                int id = e.getPointerId(idx);
                float x = e.getX(idx), y = e.getY(idx);
                Btn b = hit(x, y);
                if (b != null && b.pointer < 0) { b.pointer = id; break; }
                if (x < getWidth() * 0.45f && y > getHeight() * 0.45f && ls.pointer < 0) grab(ls, id, x, y);
                else if (x >= getWidth() * 0.45f && rs.pointer < 0) grab(rs, id, x, y);
                break;
            }
            case MotionEvent.ACTION_MOVE:
                for (int i = 0; i < e.getPointerCount(); i++) {
                    int id = e.getPointerId(i);
                    if (ls.pointer == id) drag(ls, e.getX(i), e.getY(i));
                    else if (rs.pointer == id) drag(rs, e.getX(i), e.getY(i));
                }
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP:
                release(e.getPointerId(idx));
                break;
            case MotionEvent.ACTION_CANCEL:
                for (Btn b : btns) b.pointer = -1;
                letGo(ls); letGo(rs);
                break;
            default:
                return true;
        }
        send();
        invalidate();
        return true;   // nothing reaches SDL's surface (its touches would be mouse clicks)
    }

    private void grab(Stick s, int id, float x, float y) { s.pointer = id; s.ox = s.x = x; s.oy = s.y = y; s.ax = s.ay = 128; }

    private void drag(Stick s, float x, float y) {
        float dx = (x - s.ox) / stickR, dy = (y - s.oy) / stickR;
        float len = (float) Math.hypot(dx, dy);
        if (len > 1f) {   // past the rim: the base follows the thumb, so turning round is quick
            s.ox = x - dx / len * stickR; s.oy = y - dy / len * stickR;
            dx /= len; dy /= len;
        }
        s.x = x; s.y = y;
        s.ax = Math.max(0, Math.min(255, Math.round(128 + dx * 127)));
        s.ay = Math.max(0, Math.min(255, Math.round(128 + dy * 127)));
    }

    private void letGo(Stick s) { s.pointer = -1; s.ax = s.ay = 128; }

    private void release(int id) {
        for (Btn b : btns) if (b.pointer == id) b.pointer = -1;
        if (ls.pointer == id) letGo(ls);
        if (rs.pointer == id) letGo(rs);
    }

    private void send() {
        int m = 0;
        for (Btn b : btns) if (b.pointer >= 0) m |= b.mask;
        int sticks = ls.ax | ls.ay << 8 | rs.ax << 16 | rs.ay << 24;
        if (m == sentButtons && sticks == sentSticks) return;
        sentButtons = m; sentSticks = sticks;
        try { nativeTouchPad(m, sticks); } catch (UnsatisfiedLinkError ignored) { }
    }

    @Override
    protected void onDraw(Canvas c) {
        for (Btn b : btns) {
            boolean on = b.pointer >= 0;
            fill.setColor(on ? 0x80FFFFFF : 0x28FFFFFF);
            line.setColor(on ? 0xC0FFFFFF : 0x60FFFFFF);
            if (b.round) { c.drawOval(b.r, fill); c.drawOval(b.r, line); }
            else { float rr = 0.2f * u; c.drawRoundRect(b.r, rr, rr, fill); c.drawRoundRect(b.r, rr, rr, line); }
            text.setAlpha(on ? 255 : 170);
            c.drawText(b.label, b.r.centerX(), b.r.centerY() - (text.descent() + text.ascent()) / 2, text);
        }
        drawStick(c, ls);
        drawStick(c, rs);
    }

    private void drawStick(Canvas c, Stick s) {
        boolean on = s.pointer >= 0;
        float bx = on ? s.ox : s.homeX, by = on ? s.oy : s.homeY;
        fill.setColor(on ? 0x30FFFFFF : 0x14FFFFFF);
        line.setColor(on ? 0x90FFFFFF : 0x40FFFFFF);
        c.drawCircle(bx, by, stickR, fill);
        c.drawCircle(bx, by, stickR, line);
        float kx = bx + (s.ax - 128) / 127f * stickR, ky = by + (s.ay - 128) / 127f * stickR;
        fill.setColor(on ? 0x90FFFFFF : 0x30FFFFFF);
        c.drawCircle(kx, ky, 0.45f * stickR, fill);
    }

    // ---- hidden while a real controller is connected ----

    private static boolean isGamepad(InputDevice d) {
        if (d == null || d.isVirtual()) return false;
        int src = d.getSources();
        return (src & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD ||
               (src & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK;
    }

    private void updateVisibility() {
        boolean pad = false;
        for (int id : InputDevice.getDeviceIds()) if (isGamepad(InputDevice.getDevice(id))) pad = true;
        if (pad) {
            for (Btn b : btns) b.pointer = -1;
            letGo(ls); letGo(rs);
            send();
        }
        setVisibility(pad ? GONE : VISIBLE);
    }

    @Override public void onInputDeviceAdded(int id) { updateVisibility(); }
    @Override public void onInputDeviceRemoved(int id) { updateVisibility(); }
    @Override public void onInputDeviceChanged(int id) { updateVisibility(); }
}

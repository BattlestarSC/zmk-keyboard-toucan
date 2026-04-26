#include <zephyr/kernel.h>
#include <lvgl.h>

#include <zmk/battery.h>
#include <zmk/event_manager.h>
#include <zmk/events/battery_state_changed.h>

LV_IMG_DECLARE(toucan128);

static lv_obj_t *battery_label;

static void render_battery(uint8_t level) {
    if (battery_label) {
        lv_label_set_text_fmt(battery_label, "%d%%", level);
    }
}

static int battery_listener(const zmk_event_t *eh) {
    const struct zmk_battery_state_changed *ev = as_zmk_battery_state_changed(eh);
    if (ev) {
        render_battery(ev->state_of_charge);
    }
    return 0;
}

ZMK_LISTENER(toucan_pet_battery, battery_listener);
ZMK_SUBSCRIPTION(toucan_pet_battery, zmk_battery_state_changed);

void setup_status_screen(lv_obj_t *screen) {
    lv_obj_t *img = lv_img_create(screen);
    lv_img_set_src(img, &toucan128);
    lv_obj_align(img, LV_ALIGN_TOP_MID, 0, 0);

    battery_label = lv_label_create(screen);
    lv_obj_align(battery_label, LV_ALIGN_BOTTOM_MID, 0, -4);
    render_battery(zmk_battery_state_of_charge());
}

lv_obj_t *zmk_display_status_screen() {
    lv_obj_t *screen = lv_obj_create(NULL);
    setup_status_screen(screen);
    return screen;
}

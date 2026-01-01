#include <zephyr/kernel.h>
#include <lvgl.h>

LV_IMG_DECLARE(toucan128);

void setup_status_screen(lv_obj_t *screen) {
    lv_obj_t *img = lv_img_create(screen);
    lv_img_set_src(img, &toucan128);
    lv_obj_center(img);
}

lv_obj_t *zmk_display_status_screen() {
    lv_obj_t *screen = lv_obj_create(NULL);
    setup_status_screen(screen);
    return screen;
}

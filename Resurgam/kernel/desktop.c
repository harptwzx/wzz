/* ============================================================================
 * Resurgam OS - Desktop Environment
 * Beautiful desktop with taskbar, icons, and wallpaper
 * ============================================================================ */

#include "kernel.h"
#include "vga.h"
#include "window.h"
#include "desktop.h"
#include "shell.h"
#include "mouse.h"

/* Desktop state */
desktop_icon_t* desktop_icons = 0;
taskbar_button_t* taskbar_buttons = 0;
uint32_t desktop_bg_color = 0;
int show_taskbar = 1;
int show_clock = 1;

/* Wallpaper pattern */
static uint32_t wallpaper_pattern[16][16];
static int wallpaper_initialized = 0;

/* Forward declarations */
static void icon_terminal_click(desktop_icon_t* icon);
static void icon_files_click(desktop_icon_t* icon);
static void icon_settings_click(desktop_icon_t* icon);
static void icon_calc_click(desktop_icon_t* icon);
static void icon_about_click(desktop_icon_t* icon);
static void paint_file_manager(window_t* w);
static void paint_settings(window_t* w);
static void paint_calculator(window_t* w);
static void paint_about(window_t* w);
static void paint_start_menu(window_t* w);
void show_start_menu(void);

/* ============================================================================
 * Initialize Desktop
 * ============================================================================ */
void init_desktop(void) {
    /* Generate wallpaper pattern */
    if (!wallpaper_initialized) {
        for (int y = 0; y < 16; y++) {
            for (int x = 0; x < 16; x++) {
                uint8_t r = 20 + (x * 3) + (y * 2);
                uint8_t g = 30 + (y * 4);
                uint8_t b = 50 + (x * 2) + (y * 3);
                wallpaper_pattern[y][x] = rgb(r, g, b);
            }
        }
        wallpaper_initialized = 1;
    }

    /* Add default desktop icons */
    add_desktop_icon("Terminal", 20, 20, rgb(60, 60, 60), icon_terminal_click);
    add_desktop_icon("Files", 20, 90, rgb(80, 120, 180), icon_files_click);
    add_desktop_icon("Settings", 20, 160, rgb(120, 120, 120), icon_settings_click);
    add_desktop_icon("Calculator", 20, 230, rgb(180, 140, 80), icon_calc_click);
    add_desktop_icon("About", 20, 300, rgb(100, 180, 100), icon_about_click);

    /* Draw initial desktop */
    draw_desktop();
}

/* ============================================================================
 * Draw Desktop
 * ============================================================================ */
void draw_desktop(void) {
    /* Draw wallpaper with pattern */
    for (int y = 0; y < SCREEN_HEIGHT; y++) {
        for (int x = 0; x < SCREEN_WIDTH; x++) {
            uint32_t pattern = wallpaper_pattern[y % 16][x % 16];
            /* Add subtle gradient */
            uint8_t r = ((pattern >> 16) & 0xFF) * (SCREEN_HEIGHT - y) / SCREEN_HEIGHT;
            uint8_t g = ((pattern >> 8) & 0xFF) * (SCREEN_HEIGHT - y) / SCREEN_HEIGHT;
            uint8_t b = (pattern & 0xFF) * (SCREEN_HEIGHT - y) / SCREEN_HEIGHT;
            putpixel(x, y, rgb(r, g, b));
        }
    }

    /* Draw desktop icons */
    draw_desktop_icons();

    /* Draw taskbar */
    if (show_taskbar) {
        draw_taskbar();
    }
}

/* ============================================================================
 * Draw Taskbar
 * ============================================================================ */
void draw_taskbar(void) {
    int tb_y = SCREEN_HEIGHT - TASKBAR_HEIGHT;

    /* Taskbar background with gradient */
    draw_gradient_v(0, tb_y, SCREEN_WIDTH, TASKBAR_HEIGHT,
                    rgb(40, 50, 70), rgb(30, 40, 60));

    /* Top highlight line */
    draw_rect(0, tb_y, SCREEN_WIDTH, 1, rgb(80, 100, 140));

    /* Start button */
    draw_rounded_rect(4, tb_y + 3, 60, 22, 3, rgb(60, 120, 200));
    draw_string(14, tb_y + 7, "Start", COLOR_WHITE, 1);

    /* Taskbar buttons */
    update_taskbar();

    /* Clock */
    if (show_clock) {
        draw_clock();
    }

    /* System tray area */
    draw_rect(SCREEN_WIDTH - 100, tb_y + 2, 96, 24, rgb(50, 60, 80));
    draw_rect_outline(SCREEN_WIDTH - 100, tb_y + 2, 96, 24, rgb(70, 90, 120), 1);
}

/* ============================================================================
 * Draw Clock
 * ============================================================================ */
void draw_clock(void) {
    char time_str[16];
    int tb_y = SCREEN_HEIGHT - TASKBAR_HEIGHT;

    /* Format time (simulated) */
    uint32_t seconds = timer_seconds;
    int hours = (seconds / 3600) % 24;
    int minutes = (seconds / 60) % 60;

    char h1 = '0' + (hours / 10);
    char h2 = '0' + (hours % 10);
    char m1 = '0' + (minutes / 10);
    char m2 = '0' + (minutes % 10);

    time_str[0] = h1; time_str[1] = h2;
    time_str[2] = ':';
    time_str[3] = m1; time_str[4] = m2;
    time_str[5] = 0;

    draw_string(SCREEN_WIDTH - 90, tb_y + 9, time_str, rgb(200, 200, 220), 1);
}

/* ============================================================================
 * Draw Desktop Icons
 * ============================================================================ */
void draw_desktop_icons(void) {
    desktop_icon_t* icon = desktop_icons;
    while (icon) {
        /* Icon background (transparent when not hovered) */
        draw_rounded_rect(icon->x, icon->y, ICON_SIZE, ICON_SIZE, 4, icon->color);

        /* Icon highlight */
        draw_rect(icon->x + 4, icon->y + 4, ICON_SIZE - 8, 4, rgb(255, 255, 255));

        /* Icon label */
        int label_len = strlen(icon->label);
        int label_x = icon->x + (ICON_SIZE - label_len * 8) / 2;
        draw_string(label_x, icon->y + ICON_SIZE + 2, icon->label, COLOR_WHITE, 1);

        icon = icon->next;
    }
}

/* ============================================================================
 * Add Desktop Icon
 * ============================================================================ */
void add_desktop_icon(const char* label, int x, int y, uint32_t color, void (*on_click)(desktop_icon_t*)) {
    desktop_icon_t* icon = (desktop_icon_t*)kmalloc(sizeof(desktop_icon_t));
    if (!icon) return;

    memset(icon, 0, sizeof(desktop_icon_t));
    icon->x = x;
    icon->y = y;
    icon->color = color;
    icon->on_click = on_click;
    strncpy(icon->label, label, 31);
    icon->label[31] = 0;

    icon->next = desktop_icons;
    desktop_icons = icon;
}

/* ============================================================================
 * Taskbar Buttons
 * ============================================================================ */
void add_taskbar_button(window_t* w) {
    if (!w) return;

    taskbar_button_t* btn = (taskbar_button_t*)kmalloc(sizeof(taskbar_button_t));
    if (!btn) return;

    memset(btn, 0, sizeof(taskbar_button_t));
    btn->window = w;
    strncpy(btn->label, w->title, 31);
    btn->label[31] = 0;
    btn->color = (w->flags & WF_ACTIVE) ? rgb(80, 130, 200) : rgb(60, 70, 90);

    btn->next = taskbar_buttons;
    taskbar_buttons = btn;
}

void remove_taskbar_button(window_t* w) {
    taskbar_button_t** current = &taskbar_buttons;
    while (*current) {
        if ((*current)->window == w) {
            taskbar_button_t* to_remove = *current;
            *current = (*current)->next;
            kfree(to_remove);
            return;
        }
        current = &(*current)->next;
    }
}

void update_taskbar(void) {
    int x = 70;
    int tb_y = SCREEN_HEIGHT - TASKBAR_HEIGHT;

    taskbar_button_t* btn = taskbar_buttons;
    while (btn) {
        btn->x = x;
        btn->y = tb_y + 3;
        btn->w = 120;
        btn->h = 22;

        /* Button background */
        uint32_t bg = (btn->window && btn->window->flags & WF_ACTIVE) 
                      ? rgb(80, 130, 200) : rgb(50, 60, 80);
        draw_rounded_rect(btn->x, btn->y, btn->w, btn->h, 2, bg);

        /* Button text */
        draw_string(btn->x + 8, btn->y + 6, btn->label, COLOR_WHITE, 1);

        x += 124;
        btn = btn->next;
    }
}

/* ============================================================================
 * Mouse Event Handlers
 * ============================================================================ */
void handle_mouse_move(int x, int y) {
    /* Update cursor position */
    cursor_x = x;
    cursor_y = y;

    /* Handle window dragging */
    if (drag_window && (drag_window->flags & WF_MOVABLE)) {
        move_window(drag_window, x - drag_offset_x, y - drag_offset_y);
    }
}

void handle_mouse_click(int x, int y, int button) {
    /* Check taskbar */
    if (y >= SCREEN_HEIGHT - TASKBAR_HEIGHT && show_taskbar) {
        /* Start button */
        if (x >= 4 && x < 64) {
            show_start_menu();
            return;
        }
        return;
    }

    /* Check desktop icons */
    desktop_icon_t* icon = desktop_icons;
    while (icon) {
        if (x >= icon->x && x < icon->x + ICON_SIZE &&
            y >= icon->y && y < icon->y + ICON_SIZE) {
            if (icon->on_click) icon->on_click(icon);
            return;
        }
        icon = icon->next;
    }

    /* Check windows */
    window_t* w = window_at(x, y);
    if (w) {
        activate_window(w);
        int hit = window_hit_test(w, x, y);

        switch (hit) {
            case HT_CLOSE:
                destroy_window(w);
                break;
            case HT_MINIMIZE:
                minimize_window(w);
                break;
            case HT_MAXIMIZE:
                if (w->flags & WF_MAXIMIZED) {
                    restore_window(w);
                } else {
                    maximize_window(w);
                }
                break;
            case HT_TITLEBAR:
                drag_window = w;
                drag_offset_x = x - w->x;
                drag_offset_y = y - w->y;
                break;
            case HT_CLIENT:
                if (w->on_click) {
                    w->on_click(w, x - w->x - WINDOW_BORDER, 
                               y - w->y - WINDOW_TITLE_H, button);
                }
                break;
        }
    } else {
        /* Clicked on desktop background */
        if (active_window) {
            active_window->flags &= ~WF_ACTIVE;
            active_window = 0;
        }
    }
}

void handle_mouse_release(int x, int y, int button) {
    drag_window = 0;
}

/* ============================================================================
 * Icon Click Handlers
 * ============================================================================ */
static void icon_terminal_click(desktop_icon_t* icon) {
    shell_create_window();
}

static void icon_files_click(desktop_icon_t* icon) {
    /* Open file manager */
    window_t* w = create_window("File Manager", 100, 50, 500, 350, 
                                WF_RESIZABLE | WF_MOVABLE | WF_HAS_SHADOW);
    if (w) {
        w->bg_color = rgb(250, 250, 252);
        w->on_paint = paint_file_manager;
    }
}

static void icon_settings_click(desktop_icon_t* icon) {
    window_t* w = create_window("Settings", 150, 80, 400, 300,
                                WF_RESIZABLE | WF_MOVABLE | WF_HAS_SHADOW);
    if (w) {
        w->bg_color = rgb(245, 245, 248);
        w->on_paint = paint_settings;
    }
}

static void icon_calc_click(desktop_icon_t* icon) {
    window_t* w = create_window("Calculator", 200, 100, 260, 320,
                                WF_MOVABLE | WF_HAS_SHADOW);
    if (w) {
        w->bg_color = rgb(230, 230, 235);
        w->on_paint = paint_calculator;
    }
}

static void icon_about_click(desktop_icon_t* icon) {
    window_t* w = create_window("About Resurgam", 250, 150, 350, 200,
                                WF_MOVABLE | WF_HAS_SHADOW);
    if (w) {
        w->bg_color = rgb(245, 245, 250);
        w->on_paint = paint_about;
    }
}

/* ============================================================================
 * Window Paint Handlers
 * ============================================================================ */
static void paint_file_manager(window_t* w) {
    int cx = WINDOW_BORDER;
    int cy = WINDOW_TITLE_H;
    int cw = w->width - WINDOW_BORDER * 2;
    int ch = w->height - WINDOW_TITLE_H - WINDOW_BORDER;

    /* Background */
    draw_rect(w->x + cx, w->y + cy, cw, ch, w->bg_color);

    /* Toolbar */
    draw_rect(w->x + cx, w->y + cy, cw, 28, rgb(230, 230, 235));
    draw_string(w->x + cx + 8, w->y + cy + 8, "Home  >  Documents", rgb(80, 80, 80), 1);

    /* File list area */
    draw_rect(w->x + cx, w->y + cy + 28, cw, ch - 28, COLOR_WHITE);
    draw_rect_outline(w->x + cx, w->y + cy + 28, cw, ch - 28, rgb(200, 200, 210), 1);

    /* Sample files */
    draw_string(w->x + cx + 10, w->y + cy + 40, "Documents/", rgb(80, 120, 180), 1);
    draw_string(w->x + cx + 20, w->y + cy + 58, "readme.txt", rgb(60, 60, 60), 1);
    draw_string(w->x + cx + 20, w->y + cy + 74, "notes.md", rgb(60, 60, 60), 1);
    draw_string(w->x + cx + 20, w->y + cy + 90, "project/", rgb(80, 120, 180), 1);
}

static void paint_settings(window_t* w) {
    int cx = WINDOW_BORDER;
    int cy = WINDOW_TITLE_H;

    draw_rect(w->x + cx, w->y + cy, w->width - cx * 2, 
              w->height - cy - WINDOW_BORDER, w->bg_color);

    draw_string(w->x + cx + 10, w->y + cy + 10, "System Settings", rgb(60, 60, 60), 1);
    draw_string(w->x + cx + 10, w->y + cy + 30, "----------------", rgb(180, 180, 180), 1);

    /* Settings items */
    const char* settings[] = {
        "Display", "Sound", "Network", "Users", "Security", "Updates"
    };
    for (int i = 0; i < 6; i++) {
        draw_rect(w->x + cx + 10, w->y + cy + 50 + i * 28, 200, 24, rgb(220, 220, 225));
        draw_string(w->x + cx + 18, w->y + cy + 56 + i * 28, 
                   settings[i], rgb(60, 60, 60), 1);
    }
}

static void paint_calculator(window_t* w) {
    int cx = WINDOW_BORDER;
    int cy = WINDOW_TITLE_H;
    int cw = w->width - cx * 2;

    draw_rect(w->x + cx, w->y + cy, cw, w->height - cy - WINDOW_BORDER, w->bg_color);

    /* Display */
    draw_rect(w->x + cx + 10, w->y + cy + 10, cw - 20, 40, rgb(200, 220, 180));
    draw_rect_outline(w->x + cx + 10, w->y + cy + 10, cw - 20, 40, rgb(150, 170, 130), 1);
    draw_string(w->x + cw - 50, w->y + cy + 24, "0", rgb(40, 60, 30), 1);

    /* Buttons */
    const char* buttons[] = {
        "7", "8", "9", "/",
        "4", "5", "6", "*",
        "1", "2", "3", "-",
        "0", ".", "=", "+"
    };
    for (int row = 0; row < 4; row++) {
        for (int col = 0; col < 4; col++) {
            int bx = w->x + cx + 10 + col * 55;
            int by = w->y + cy + 60 + row * 45;
            draw_rounded_rect(bx, by, 50, 40, 3, rgb(240, 240, 245));
            draw_rect_outline(bx, by, 50, 40, rgb(200, 200, 210), 1);
            draw_string(bx + 20, by + 14, buttons[row * 4 + col], rgb(60, 60, 60), 1);
        }
    }
}

static void paint_about(window_t* w) {
    int cx = WINDOW_BORDER;
    int cy = WINDOW_TITLE_H;
    int cw = w->width - cx * 2;
    int ch = w->height - cy - WINDOW_BORDER;

    draw_rect(w->x + cx, w->y + cy, cw, ch, w->bg_color);

    /* Logo */
    draw_circle(w->x + cw / 2, w->y + cy + 50, 30, rgb(100, 150, 255));
    draw_string_large(w->x + cw / 2 - 80, w->y + cy + 90, "Resurgam OS", rgb(60, 100, 180));

    draw_string_centered(w->y + cy + 130, "Version 1.0", rgb(100, 100, 100));
    draw_string_centered(w->y + cy + 148, "32-bit Graphical Operating System", rgb(100, 100, 100));
    draw_string_centered(w->y + cy + 166, "Built with C and Assembly", rgb(100, 100, 100));

    draw_string_centered(w->y + cy + 190, "(C) 2026 Resurgam Project", rgb(120, 120, 120));
}

/* ============================================================================
 * Start Menu
 * ============================================================================ */
static void show_start_menu(void) {
    /* Create a temporary menu window */
    window_t* menu = create_window("", 4, SCREEN_HEIGHT - TASKBAR_HEIGHT - 200, 
                                   200, 200, WF_HAS_SHADOW);
    if (menu) {
        menu->y = SCREEN_HEIGHT - TASKBAR_HEIGHT - 200;
        menu->bg_color = rgb(245, 245, 250);
        menu->on_paint = paint_start_menu;
    }
}

static void paint_start_menu(window_t* w) {
    int cx = WINDOW_BORDER;
    int cy = WINDOW_TITLE_H;

    draw_rect(w->x + cx, w->y + cy, w->width - cx * 2, 
              w->height - cy - WINDOW_BORDER, w->bg_color);

    const char* items[] = {
        "Terminal", "File Manager", "Calculator", 
        "Settings", "About", "Restart", "Shutdown"
    };
    for (int i = 0; i < 7; i++) {
        draw_string(w->x + cx + 10, w->y + cy + 10 + i * 24, 
                   items[i], rgb(60, 60, 60), 1);
    }
}

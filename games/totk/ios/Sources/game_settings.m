#import "game_settings.h"
#import "touch_pad.h"
#import <MetalFX/MetalFX.h>
#include "runtime.h"
#include "settings_map.h"
#include "fps_overlay.h"
#include "totk_mfx_up.h"
#include "totk_taa.h"
#include "game_version.h"
#include "totk_ui_lang.h"
#include <math.h>

static NSString *T(NSString *zh, NSString *en) { return totk_ui_zh() ? zh : en; }
/* Root.plist holds the same bilingual strings used by the system Settings pane. */
static NSString *paneText(NSString *text) {
    if (![text isKindOfClass:NSString.class]) return text;
    NSRange r = [text rangeOfString:@" · " options:NSBackwardsSearch];
    return r.location == NSNotFound ? text : (totk_ui_zh() ? [text substringToIndex:r.location] : [text substringFromIndex:NSMaxRange(r)]);
}

/* The system Settings bundle owns the choices and their defaults. This panel reads the same rows. */
@interface TOTKGameSettingsController : UITableViewController
@property(nonatomic, weak) TOTKTouchPad *pad;
@property(nonatomic, strong) NSDictionary *rows;
@property(nonatomic, strong) NSDictionary *launched;
@property(nonatomic, strong) NSTimer *statusTimer;
@end

static NSDictionary *launchSettings;
static NSSet<NSString *> *fixedSettings;
void totk_capture_settings_environment(void) {
    NSMutableSet *fixed = [NSMutableSet set];
    for (NSString *key in @[@"TOTK_RENDER_RES", @"TOTK_MFX_UPSCALE", @"TOTK_TAA", @"TOTK_FPS_OVERLAY", @"TOTK_SHADER_OVERLAY"])
        if (getenv(key.UTF8String)) [fixed addObject:key];
    fixedSettings = fixed;
}
static unsigned cheatBit(NSString *key) {
    if ([key isEqual:@"TOTK_CHEAT_HEALTH"]) return 1;
    if ([key isEqual:@"TOTK_CHEAT_BATTERY"]) return 2;
    if ([key isEqual:@"TOTK_CHEAT_STAMINA"]) return 4;
    return 0;
}
void totk_restore_cheats(void) {
#if defined(TOTK_GAME_V143) && !defined(GAME_BOTW)
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults; unsigned flags = 0;
    for (NSString *key in @[@"TOTK_CHEAT_HEALTH", @"TOTK_CHEAT_BATTERY", @"TOTK_CHEAT_STAMINA"])
        if ([d boolForKey:key]) flags |= cheatBit(key);
    runtime_cheat_set(flags);
#endif
}
void totk_capture_game_settings(void) {
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    launchSettings = @{@"TOTK_CUSTOM_PICTURE": @([d boolForKey:@"TOTK_CUSTOM_PICTURE"]),
                       @"TOTK_IOS_PICTURE_MODE": [d stringForKey:@"TOTK_IOS_PICTURE_MODE"] ?: @"720",
                       @"TOTK_RENDER_RES": [d stringForKey:@"TOTK_RENDER_RES"] ?: @"960x540"};
}
@implementation TOTKGameSettingsController
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = T(@"设置", @"Settings");
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemDone target:self action:@selector(done)];
    NSString *path = [[NSBundle.mainBundle pathForResource:@"Settings" ofType:@"bundle"] stringByAppendingPathComponent:@"Root.plist"];
    NSMutableDictionary *r = [NSMutableDictionary dictionary];
    for (NSDictionary *row in [NSDictionary dictionaryWithContentsOfFile:path][@"PreferenceSpecifiers"]) if (row[@"Key"]) r[row[@"Key"]] = row;
    self.rows = r;
    if (!launchSettings) totk_capture_game_settings();
    self.launched = launchSettings;
}
- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
#if defined(TOTK_GAME_V143) && !defined(GAME_BOTW)
    if (!runtime_cheat_hooks_ready()) {
        __weak TOTKGameSettingsController *weak = self;
        self.statusTimer = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *timer) {
            TOTKGameSettingsController *controller = weak;
            if (!controller || runtime_cheat_hooks_ready()) { [timer invalidate]; if (controller) { controller.statusTimer = nil; [controller.tableView reloadData]; } }
        }];
    }
#endif
}
- (void)viewDidDisappear:(BOOL)animated { [super viewDidDisappear:animated]; [self.statusTimer invalidate]; self.statusTimer = nil; }
- (void)closeWithCompletion:(void (^)(void))completion {
    UIViewController *overlay = self.navigationController.parentViewController ?: self.navigationController;
    fprintf(stderr, "[totk] settings panel closing\n");
    [overlay dismissViewControllerAnimated:YES completion:completion];
}
- (void)done { [self closeWithCompletion:^{ [self.pad showControls]; }]; }
- (NSArray *)keys:(NSInteger)section {
    if (section == 0) return @[@"TOTK_AUTO_START", @"TOTK_CUSTOM_PICTURE", @"TOTK_IOS_PICTURE_MODE", @"TOTK_RENDER_RES", @"TOTK_FPS_CAP", @"TOTK_PHONE_FPS"];
    if (section == 1) return @[@"TOTK_MFX_UPSCALE", @"TOTK_TAA"];
    if (section == 2) return @[@"TOTK_FPS_OVERLAY", @"TOTK_SHADER_OVERLAY"];
    if (section == 3) return @[@"layout", @"TOTK_TOUCH_OPACITY"];
    return @[@"TOTK_CHEAT_HEALTH", @"TOTK_CHEAT_STAMINA", @"TOTK_CHEAT_BATTERY"];
}
- (NSInteger)numberOfSectionsInTableView:(UITableView *)tableView { (void)tableView; return 5; }
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { (void)tableView; return [self keys:section].count; }
- (NSString *)tableView:(UITableView *)tableView titleForHeaderInSection:(NSInteger)section { (void)tableView; return @[T(@"启动与画质帧率", @"Startup, picture and frame rate"), @"MetalFX", T(@"界面", @"Interface"), T(@"触控布局", @"Touch controls"), T(@"作弊", @"Cheats")][section]; }
- (NSString *)tableView:(UITableView *)tableView titleForFooterInSection:(NSInteger)section {
    (void)tableView;
    if (section == 0) return T(@"自动进入、画质模式、场景分辨率和自定义模式在下次启动生效。", @"Auto-start, picture mode, scene resolution and custom mode take effect at the next launch.");
    if (section == 4) return T(@"实验功能：尚未确认是否影响其他对象；特殊死亡、额外体力和试炼可能不受影响。关闭后不回退已改变的状态。", @"Experimental: effects on other objects and coverage of special situations are unverified; disabling does not restore changed values.");
    return nil;
}
- (id)value:(NSString *)key { return [NSUserDefaults.standardUserDefaults objectForKey:key] ?: self.rows[key][@"DefaultValue"]; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)index {
    (void)tableView; NSString *key = [self keys:index.section][index.row];
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleSubtitle reuseIdentifier:nil];
    cell.textLabel.numberOfLines = 0; cell.detailTextLabel.numberOfLines = 0;
    if ([key isEqual:@"layout"]) { cell.textLabel.text = T(@"编辑控制位置", @"Edit control positions"); cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator; return cell; }
    if ([key isEqual:@"TOTK_TOUCH_OPACITY"]) {
        cell.textLabel.text = T(@"虚拟按键不透明度", @"Touch control opacity");
        id saved = [NSUserDefaults.standardUserDefaults objectForKey:key]; float value = totk_touch_opacity([saved floatValue], saved != nil);
        UISlider *slider = [UISlider new]; slider.minimumValue = 0.1f; slider.maximumValue = 1.0f; slider.value = value;
        slider.accessibilityLabel = cell.textLabel.text; slider.frame = CGRectMake(0, 0, 150, 32);
        [slider addTarget:self action:@selector(opacityChanged:) forControlEvents:UIControlEventValueChanged]; cell.accessoryView = slider;
        cell.detailTextLabel.text = [NSString stringWithFormat:@"%.0f%%", slider.value * 100]; cell.selectionStyle = UITableViewCellSelectionStyleNone; return cell;
    }
    if ([key isEqual:@"TOTK_AUTO_START"]) {
        cell.textLabel.text = T(@"打开应用后直接进入游戏", @"Start game automatically");
        cell.detailTextLabel.text = T(@"下次启动生效", @"Applies at next launch");
        UISwitch *sw = [UISwitch new]; sw.on = [NSUserDefaults.standardUserDefaults boolForKey:key]; sw.accessibilityIdentifier = key;
        [sw addTarget:self action:@selector(changed:) forControlEvents:UIControlEventValueChanged]; cell.accessoryView = sw; cell.selectionStyle = UITableViewCellSelectionStyleNone; return cell;
    }
    if (index.section == 4) {
        cell.textLabel.text = @{@"TOTK_CHEAT_HEALTH":T(@"无限生命", @"Infinite health"), @"TOTK_CHEAT_STAMINA":T(@"无限体力", @"Infinite stamina"), @"TOTK_CHEAT_BATTERY":T(@"无限电池", @"Infinite battery")}[key];
        UISwitch *sw = [UISwitch new]; sw.on = [NSUserDefaults.standardUserDefaults boolForKey:key]; sw.accessibilityIdentifier = key;
#if defined(TOTK_GAME_V143) && !defined(GAME_BOTW)
        BOOL ready = runtime_cheat_hooks_ready(), available = (runtime_cheat_hooks_available() & cheatBit(key)) != 0;
        sw.enabled = !ready || available;
        cell.detailTextLabel.text = !ready ? T(@"等待游戏初始化", @"Waiting for game") : !available ? T(@"当前版本不可用", @"Unavailable") : sw.on ? T(@"已开启", @"On") : T(@"已关闭", @"Off");
#else
        sw.enabled = NO; cell.detailTextLabel.text = T(@"当前版本不支持", @"Unsupported");
#endif
        [sw addTarget:self action:@selector(changed:) forControlEvents:UIControlEventValueChanged]; cell.accessoryView = sw; cell.selectionStyle = UITableViewCellSelectionStyleNone; return cell;
    }
    NSDictionary *row = self.rows[key]; cell.textLabel.text = paneText(row[@"Title"]) ?: key;
    BOOL fixed = [fixedSettings containsObject:key];
    BOOL isSwitch = [row[@"Type"] isEqualToString:@"PSToggleSwitchSpecifier"];
    if (isSwitch) {
        UISwitch *sw = [UISwitch new]; sw.on = [[self value:key] boolValue]; sw.accessibilityIdentifier = key;
        if (fixed) {
            const char *actual = getenv(key.UTF8String); sw.on = actual && strcmp(actual, "0"); sw.enabled = NO;
            cell.detailTextLabel.text = T(@"由启动参数固定", @"Fixed by launch environment");
        }
        if ([key isEqual:@"TOTK_MFX_UPSCALE"] || [key isEqual:@"TOTK_TAA"]) {
            id<MTLDevice> device = MTLCreateSystemDefaultDevice();
            BOOL supported = device && ([key isEqual:@"TOTK_TAA"] ? [MTLFXTemporalScalerDescriptor supportsMetal4FX:device] : [MTLFXSpatialScalerDescriptor supportsMetal4FX:device]);
            if (!supported) { sw.enabled = NO; cell.detailTextLabel.text = T(@"当前设备不支持此 MetalFX 效果", @"Unsupported on this device"); }
            else if (sw.on && !fixed) cell.detailTextLabel.text = T(@"已启用；实际效果取决于当前场景", @"Requested; effect depends on the current scene");
        }
        if ([key isEqual:@"TOTK_MFX_UPSCALE"] && mfxup_output_enabled()) { sw.on = YES; sw.enabled = NO; }
        [sw addTarget:self action:@selector(changed:) forControlEvents:UIControlEventValueChanged]; cell.accessoryView = sw; cell.selectionStyle = UITableViewCellSelectionStyleNone;
    } else {
        NSArray *values = row[@"Values"], *titles = row[@"Titles"]; NSUInteger i = [values indexOfObject:[self value:key]];
        cell.detailTextLabel.text = i != NSNotFound && i < titles.count ? paneText(titles[i]) : T(@"不可用", @"Unavailable");
        cell.accessoryType = fixed ? UITableViewCellAccessoryNone : UITableViewCellAccessoryDisclosureIndicator;
        if (fixed) cell.detailTextLabel.text = [NSString stringWithFormat:T(@"启动参数固定：%s", @"Fixed by launch environment: %s"), getenv(key.UTF8String)];
    }
    if (self.launched[key] && !fixed) {
        id active = self.launched[key], saved = [self value:key];
        if (active && ![active isEqual:saved]) cell.detailTextLabel.text = [NSString stringWithFormat:T(@"%@ · 重启生效（当前：%@）", @"%@ · Restart required (active: %@)"), cell.detailTextLabel.text ?: T(@"已保存", @"Saved"), active];
    }
    if ([key isEqual:@"TOTK_FPS_CAP"] && ![self.launched[@"TOTK_CUSTOM_PICTURE"] boolValue]) cell.detailTextLabel.text = [cell.detailTextLabel.text stringByAppendingString:T(@" · 开启自定义模式并重启后生效", @" · Applies after enabling custom mode and restarting")];
    if ([key isEqual:@"TOTK_PHONE_FPS"] && [self.launched[@"TOTK_CUSTOM_PICTURE"] boolValue]) cell.detailTextLabel.text = [cell.detailTextLabel.text stringByAppendingString:T(@" · 预设将在重启后生效", @" · Preset inactive until restart")];
    if ([key isEqual:@"TOTK_MFX_UPSCALE"] && mfxup_output_enabled()) {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        cell.detailTextLabel.text = device && [MTLFXSpatialScalerDescriptor supportsMetal4FX:device]
            ? T(@"当前 MetalFX 2K 模式需要此项", @"Required by MetalFX 2K") : T(@"当前设备不支持此 MetalFX 效果", @"Unsupported on this device");
    }
    return cell;
}
- (void)opacityChanged:(UISlider *)slider {
    [NSUserDefaults.standardUserDefaults setFloat:slider.value forKey:@"TOTK_TOUCH_OPACITY"];
    [self.pad setNeedsDisplay];
    UITableViewCell *cell = [self.tableView cellForRowAtIndexPath:[NSIndexPath indexPathForRow:1 inSection:3]];
    cell.detailTextLabel.text = [NSString stringWithFormat:@"%.0f%%", slider.value * 100];
}
- (void)changed:(UISwitch *)sw {
    NSString *key = sw.accessibilityIdentifier; [NSUserDefaults.standardUserDefaults setBool:sw.on forKey:key];
    if (cheatBit(key)) totk_restore_cheats();
    else if ([key isEqual:@"TOTK_MFX_UPSCALE"] && !mfxup_output_enabled()) mfxup_set(sw.on);
    else if ([key isEqual:@"TOTK_TAA"]) taa_set(sw.on);
    else if ([key isEqual:@"TOTK_FPS_OVERLAY"]) fps_overlay_set_enabled(sw.on);
    else if ([key isEqual:@"TOTK_SHADER_OVERLAY"]) shader_overlay_set_enabled(sw.on);
    [self.tableView reloadData];
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)index {
    [tableView deselectRowAtIndexPath:index animated:YES]; NSString *key = [self keys:index.section][index.row];
    if ([fixedSettings containsObject:key]) return;
    if ([key isEqual:@"layout"]) { [self closeWithCompletion:^{ [self.pad beginLayoutEditing]; }]; return; }
    NSDictionary *row = self.rows[key]; NSArray *values = row[@"Values"], *titles = row[@"Titles"]; if (!values.count) return;
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:paneText(row[@"Title"]) message:nil preferredStyle:UIAlertControllerStyleActionSheet];
    for (NSUInteger i = 0; i < values.count && i < titles.count; i++) {
        id value = values[i]; [alert addAction:[UIAlertAction actionWithTitle:paneText(titles[i]) style:UIAlertActionStyleDefault handler:^(UIAlertAction *a) {
            (void)a; [NSUserDefaults.standardUserDefaults setObject:value forKey:key];
            if ([key isEqual:@"TOTK_FPS_CAP"] && [self.launched[@"TOTK_CUSTOM_PICTURE"] boolValue]) runtime_phone_fps_set([value intValue]);
            if ([key isEqual:@"TOTK_PHONE_FPS"] && ![self.launched[@"TOTK_CUSTOM_PICTURE"] boolValue]) runtime_phone_fps_set([value intValue]);
            [self.tableView reloadData];
        }]];
    }
    [alert addAction:[UIAlertAction actionWithTitle:T(@"取消", @"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    alert.popoverPresentationController.sourceView = [tableView cellForRowAtIndexPath:index];
    alert.popoverPresentationController.sourceRect = [tableView cellForRowAtIndexPath:index].bounds;
    [self presentViewController:alert animated:YES completion:nil];
}
@end

/* Keep the Metal and touch views in the window while a compact panel covers only part of the game. */
@interface TOTKSettingsOverlay : UIViewController
@property(nonatomic, strong) UINavigationController *navigation;
@end
@implementation TOTKSettingsOverlay
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.opaque = NO; self.view.backgroundColor = UIColor.clearColor;
    [self addChildViewController:self.navigation];
    UIView *panel = self.navigation.view; panel.translatesAutoresizingMaskIntoConstraints = NO;
    panel.layer.cornerRadius = 16; panel.layer.masksToBounds = YES;
    [self.view addSubview:panel];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    NSLayoutConstraint *preferredWidth = [panel.widthAnchor constraintEqualToAnchor:safe.widthAnchor multiplier:0.72];
    preferredWidth.priority = UILayoutPriorityDefaultHigh;
    [NSLayoutConstraint activateConstraints:@[
        [panel.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor], [panel.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [panel.widthAnchor constraintLessThanOrEqualToConstant:560], [panel.widthAnchor constraintLessThanOrEqualToAnchor:safe.widthAnchor constant:-24], preferredWidth,
        [panel.heightAnchor constraintEqualToAnchor:safe.heightAnchor multiplier:0.92]
    ]];
    [self.navigation didMoveToParentViewController:self];
}
@end

void totk_show_game_settings(UIViewController *parent, TOTKTouchPad *pad) {
    if (parent.presentedViewController) { [pad showControls]; return; }
    TOTKGameSettingsController *settings = [[TOTKGameSettingsController alloc] initWithStyle:UITableViewStyleInsetGrouped]; settings.pad = pad;
    UINavigationController *navigation = [[UINavigationController alloc] initWithRootViewController:settings];
    navigation.overrideUserInterfaceStyle = UIUserInterfaceStyleDark;
    TOTKSettingsOverlay *overlay = [TOTKSettingsOverlay new]; overlay.navigation = navigation;
    overlay.modalPresentationStyle = UIModalPresentationOverFullScreen;
    overlay.modalTransitionStyle = UIModalTransitionStyleCrossDissolve;
    fprintf(stderr, "[totk] settings panel opening over game\n");
    [parent presentViewController:overlay animated:YES completion:nil];
}

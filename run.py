import os
from PIL import Image, UnidentifiedImageError
import shutil
import logging
import configparser

try:
    from tqdm import tqdm  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - graceful fallback when tqdm is absent
    class _SimpleTqdm:  # minimal stand-in used only when tqdm isn't installed
        def __init__(self, iterable=None, total=None, desc=None, unit=None, **kwargs):
            self.iterable = iterable
            self.total = total
            self.desc = desc
            self.unit = unit or ""
            self.count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.close()

        def __iter__(self):
            if self.iterable is None:
                return iter(())
            for item in self.iterable:
                yield item

        def update(self, n=1):
            self.count += n

        def close(self):
            if self.total is not None and self.desc:
                print(f"{self.desc}完成: {self.count}/{self.total}{self.unit}")

    tqdm = _SimpleTqdm
import multiprocessing
import time

# --- 默认配置值 ---
DEFAULT_CONFIG = {
    'Settings': {
        'target_height': '3200',
        'target_width': '0',
        'max_height': '0',
        'max_width': '0',
        'resize_mode': 'fixed_height',
        'output_format_for_others': 'jpeg', # 当源不是JPG/PNG时的默认输出格式
        'jpeg_quality': '90',
        'enable_double_page_split': 'false',
        'split_order_is_left_to_right': 'true',
        'overwrite_existing_output_folders': 'false', # 此选项现在作用于 input_root/new/mirrored_subfolder/
        'dry_run': 'false',
        'log_filename': 'manga_processing.log', # 日志文件名，将保存在输入根目录
        'num_processes': str(max(1, (os.cpu_count() or 1) - 1)) 
    },
    'Filenames': {
        'template_single': '{base}{ext}',
        'template_split_page1': '{base}_p1{ext}',
        'template_split_page2': '{base}_p2{ext}'
    }
}

# 全局变量存储当前配置，以便保存时使用
current_config_to_save = configparser.ConfigParser()
NEW_ROOT_OUTPUT_SUBFOLDER_NAME = "new" # 新的总输出根目录的子文件夹名 (相对于input_folder)
CONFIG_FILENAME = "config.ini" # 配置文件名


def initialize_config_parser():
    """创建包含默认值的配置解析器。"""
    parser = configparser.ConfigParser()
    for section, options in DEFAULT_CONFIG.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in options.items():
            parser.set(section, key, value)
    return parser


def read_config_file(config_file_path_abs):
    """读取配置文件并在缺失时应用默认值。"""
    parser = initialize_config_parser()
    if os.path.exists(config_file_path_abs):
        parser.read(config_file_path_abs, encoding='utf-8')
    return parser


def save_config_parser(parser, config_file_path_abs):
    """将配置写入指定路径。"""
    with open(config_file_path_abs, 'w', encoding='utf-8') as configfile:
        parser.write(configfile)


def config_parser_to_dict(config_parser, input_folder_root):
    """将 ConfigParser 配置转换为处理流程使用的字典。"""
    settings_proxy = config_parser['Settings']
    filenames_cfg_proxy = config_parser['Filenames']
    return {
        'input_folder_root': input_folder_root,
        'is_dry_run': settings_proxy.getboolean('dry_run'),
        'log_filename': settings_proxy.get('log_filename'),
        'num_processes': settings_proxy.getint('num_processes'),
        'resize_mode': settings_proxy.get('resize_mode'),
        'target_height': settings_proxy.getint('target_height'),
        'target_width': settings_proxy.getint('target_width'),
        'max_height': settings_proxy.getint('max_height'),
        'max_width': settings_proxy.getint('max_width'),
        'output_format_for_others': settings_proxy.get('output_format_for_others'),
        'jpeg_quality': settings_proxy.getint('jpeg_quality'),
        'enable_double_page_split': settings_proxy.getboolean('enable_double_page_split'),
        'split_left_to_right': settings_proxy.getboolean('split_order_is_left_to_right'),
        'overwrite_existing': settings_proxy.getboolean('overwrite_existing_output_folders'),
        'template_single': filenames_cfg_proxy.get('template_single'),
        'template_split_page1': filenames_cfg_proxy.get('template_split_page1'),
        'template_split_page2': filenames_cfg_proxy.get('template_split_page2')
    }

def get_script_directory():
    """获取当前运行脚本所在的目录"""
    # __file__ 是当前文件的路径。os.path.abspath确保我们得到绝对路径。
    # os.path.dirname获取该路径的目录部分。
    return os.path.dirname(os.path.abspath(__file__))

def setup_logging(log_path, is_dry_run, *, additional_handlers=None, include_console=True):
    """配置日志记录器"""
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    log_mode = 'w'
    handlers = [logging.FileHandler(log_path, mode=log_mode, encoding='utf-8')]
    if include_console:
        handlers.append(logging.StreamHandler())
    if additional_handlers:
        handlers.extend(additional_handlers)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

def load_or_get_config(config_file_path_abs, input_folder_root_path): # config_file_path_abs 是绝对路径
    """加载配置，如果不存在或不完整则提示用户并使用默认值"""
    global current_config_to_save
    current_config_to_save = read_config_file(config_file_path_abs)

    if os.path.exists(config_file_path_abs):
        print(f"已从 '{config_file_path_abs}' 加载配置。")
    else:
        print(f"配置文件 '{config_file_path_abs}' 未找到，将使用默认设置并提示。")

    settings_proxy = current_config_to_save['Settings']
    filenames_cfg_proxy = current_config_to_save['Filenames']

    # --- Settings ---
    default_dry_run = DEFAULT_CONFIG['Settings']['dry_run'].lower() == 'true'
    is_dry_run = settings_proxy.getboolean('dry_run', fallback=default_dry_run)
    dry_run_choice = input(f"是否启用“试运行”模式? (y/n) (当前: {'y' if is_dry_run else 'n'}): ").lower().strip()
    if dry_run_choice in ['y', 'n']: is_dry_run = (dry_run_choice == 'y')
    settings_proxy['dry_run'] = str(is_dry_run).lower()

    default_log_filename = DEFAULT_CONFIG['Settings']['log_filename']
    log_filename = settings_proxy.get('log_filename', fallback=default_log_filename)
    # 用户可以修改日志文件名，但它仍然保存在输入根目录
    user_log_filename = input(f"请输入日志文件名 (将保存在输入漫画根目录下, 当前: {log_filename}): ").strip()
    if user_log_filename: log_filename = user_log_filename
    settings_proxy['log_filename'] = log_filename
    
    default_num_processes = int(DEFAULT_CONFIG['Settings']['num_processes'])
    num_processes = settings_proxy.getint('num_processes', fallback=default_num_processes)
    user_num_processes = input(f"请输入并行处理的进程数 (推荐 <= CPU核心数, 当前: {num_processes}): ").strip()
    if user_num_processes:
        try:
            num_processes_val = int(user_num_processes)
            if num_processes_val >= 1: num_processes = num_processes_val
            else: print(f"进程数至少为1，将使用当前值: {num_processes}")
        except ValueError:
            print(f"无效的进程数，将使用当前值: {num_processes}")
    settings_proxy['num_processes'] = str(num_processes)

    resize_modes = ['fixed_height', 'fixed_width', 'fit_bounds', 'none']
    default_resize_mode = DEFAULT_CONFIG['Settings']['resize_mode']
    resize_mode = settings_proxy.get('resize_mode', fallback=default_resize_mode)
    user_resize_mode = input(f"请选择图片调整模式 ({', '.join(resize_modes)}) (当前: {resize_mode}): ").lower().strip()
    if user_resize_mode and user_resize_mode in resize_modes: resize_mode = user_resize_mode
    settings_proxy['resize_mode'] = resize_mode
    
    default_target_height = int(DEFAULT_CONFIG['Settings']['target_height'])
    target_height = settings_proxy.getint('target_height', fallback=default_target_height)
    if resize_mode == 'fixed_height':
        user_val = input(f"请输入目标高度 (像素, 当前: {target_height}): ").strip()
        if user_val: 
            try: target_height = int(user_val)
            except ValueError: print(f"无效高度，使用当前值: {target_height}")
    settings_proxy['target_height'] = str(target_height)

    default_target_width = int(DEFAULT_CONFIG['Settings']['target_width'])
    target_width = settings_proxy.getint('target_width', fallback=default_target_width)
    if resize_mode == 'fixed_width':
        user_val = input(f"请输入目标宽度 (像素, 当前: {target_width}): ").strip()
        if user_val: 
            try: target_width = int(user_val)
            except ValueError: print(f"无效宽度，使用当前值: {target_width}")
    settings_proxy['target_width'] = str(target_width)
    
    default_max_height = int(DEFAULT_CONFIG['Settings']['max_height'])
    max_height = settings_proxy.getint('max_height', fallback=default_max_height)
    default_max_width = int(DEFAULT_CONFIG['Settings']['max_width'])
    max_width = settings_proxy.getint('max_width', fallback=default_max_width)
    if resize_mode == 'fit_bounds':
        user_val_h = input(f"请输入最大高度 (像素, 当前: {max_height}): ").strip()
        if user_val_h: 
            try: max_height = int(user_val_h)
            except ValueError: print(f"无效最大高度，使用当前值: {max_height}")
        user_val_w = input(f"请输入最大宽度 (像素, 当前: {max_width}): ").strip()
        if user_val_w: 
            try: max_width = int(user_val_w)
            except ValueError: print(f"无效最大宽度，使用当前值: {max_width}")
    settings_proxy['max_height'] = str(max_height)
    settings_proxy['max_width'] = str(max_width)

    output_formats_for_others = ['jpeg', 'png']
    default_output_format_for_others = DEFAULT_CONFIG['Settings']['output_format_for_others']
    output_format_for_others = settings_proxy.get('output_format_for_others', fallback=default_output_format_for_others)
    user_output_format_for_others = input(f"当源文件不是JPG/JPEG/PNG时, 请选择默认输出格式 ({'/'.join(output_formats_for_others)}) (当前: {output_format_for_others}): ").lower().strip()
    if user_output_format_for_others and user_output_format_for_others in output_formats_for_others:
        output_format_for_others = user_output_format_for_others
    settings_proxy['output_format_for_others'] = output_format_for_others
    
    default_jpeg_quality = int(DEFAULT_CONFIG['Settings']['jpeg_quality'])
    jpeg_quality = settings_proxy.getint('jpeg_quality', fallback=default_jpeg_quality)
    if output_format_for_others == 'jpeg' or any(s.lower().endswith(('.jpg', '.jpeg')) for s in ['test.jpg']): 
        user_jpeg_quality = input(f"请输入JPEG图片质量 (1-100, 当前: {jpeg_quality}): ").strip()
        if user_jpeg_quality:
            try:
                jpeg_quality_val = int(user_jpeg_quality)
                if 1 <= jpeg_quality_val <= 100: jpeg_quality = jpeg_quality_val
                else: print(f"JPEG质量无效，使用当前值: {jpeg_quality}")
            except ValueError: print(f"无效JPEG质量，使用当前值: {jpeg_quality}")
    settings_proxy['jpeg_quality'] = str(jpeg_quality)

    default_enable_split = DEFAULT_CONFIG['Settings']['enable_double_page_split'].lower() == 'true'
    enable_split = settings_proxy.getboolean('enable_double_page_split', fallback=default_enable_split)
    enable_choice = input(f"是否启用双页切割? (y/n) (当前: {'y' if enable_split else 'n'}): ").lower().strip()
    if enable_choice in ['y', 'n']:
        enable_split = (enable_choice == 'y')
    settings_proxy['enable_double_page_split'] = str(enable_split).lower()

    default_split_left_to_right = DEFAULT_CONFIG['Settings']['split_order_is_left_to_right'].lower() == 'true'
    split_left_to_right = settings_proxy.getboolean('split_order_is_left_to_right', fallback=default_split_left_to_right)
    if enable_split:
        order_choice = input(f"切割顺序 (1: 左到右, 2: 右到左) (当前: {'1' if split_left_to_right else '2'}): ").strip()
        if order_choice in ['1', '2']:
            split_left_to_right = (order_choice == '1')
    settings_proxy['split_order_is_left_to_right'] = str(split_left_to_right).lower()

    default_overwrite_existing = DEFAULT_CONFIG['Settings']['overwrite_existing_output_folders'].lower() == 'true'
    overwrite_existing = settings_proxy.getboolean('overwrite_existing_output_folders', fallback=default_overwrite_existing)
    overwrite_prompt = (f"如果目标镜像文件夹 (例如 '{input_folder_root_path}/{NEW_ROOT_OUTPUT_SUBFOLDER_NAME}/[子文件夹]/') "
                        f"已存在，是否清空并覆盖其内容? (y/n) (当前: {'y' if overwrite_existing else 'n'}): ")
    overwrite_choice = input(overwrite_prompt).lower().strip()
    if overwrite_choice in ['y', 'n']: overwrite_existing = (overwrite_choice == 'y')
    settings_proxy['overwrite_existing_output_folders'] = str(overwrite_existing).lower()

    # --- Filenames ---
    default_template_single = DEFAULT_CONFIG['Filenames']['template_single']
    template_single = filenames_cfg_proxy.get('template_single', fallback=default_template_single)
    user_template_single = input(f"单页图片文件名模板 (当前: {template_single}): ").strip()
    if user_template_single: template_single = user_template_single
    filenames_cfg_proxy['template_single'] = template_single
    
    default_template_split1 = DEFAULT_CONFIG['Filenames']['template_split_page1']
    template_split_page1 = filenames_cfg_proxy.get('template_split_page1', fallback=default_template_split1)
    user_template_split1 = input(f"切割后第一页文件名模板 (当前: {template_split_page1}): ").strip()
    if user_template_split1: template_split_page1 = user_template_split1
    filenames_cfg_proxy['template_split_page1'] = template_split_page1

    default_template_split2 = DEFAULT_CONFIG['Filenames']['template_split_page2']
    template_split_page2 = filenames_cfg_proxy.get('template_split_page2', fallback=default_template_split2)
    user_template_split2 = input(f"切割后第二页文件名模板 (当前: {template_split_page2}): ").strip()
    if user_template_split2: template_split_page2 = user_template_split2
    filenames_cfg_proxy['template_split_page2'] = template_split_page2

    save_conf_choice = input(f"是否将当前设置保存到 '{config_file_path_abs}' (与脚本同目录)? (y/n): ").lower().strip()
    if save_conf_choice == 'y':
        try:
            save_config_parser(current_config_to_save, config_file_path_abs)
            print(f"配置已保存到 '{config_file_path_abs}'。")
        except IOError:
            print(f"错误：无法保存配置文件到 '{config_file_path_abs}'。请检查脚本目录的写入权限。")

    return config_parser_to_dict(current_config_to_save, input_folder_root_path)

def get_dynamic_output_format_and_ext(original_ext_lower, config):
    if original_ext_lower in ['.jpg', '.jpeg']: return 'JPEG', '.jpg'
    if original_ext_lower == '.png': return 'PNG', '.png'
    default_format = config['output_format_for_others']
    return default_format.upper(), '.jpg' if default_format == 'jpeg' else '.png'

def get_all_image_files(input_folder, supported_formats, log_filename_val):
    """收集所有需要处理的图片文件路径, 跳过日志文件, 以及 input_folder/new/ 目录"""
    all_files_to_process = []
    # new_output_dir_to_skip_abs 是 input_folder 下的 "new" 目录
    new_output_dir_to_skip_abs = os.path.abspath(os.path.join(input_folder, NEW_ROOT_OUTPUT_SUBFOLDER_NAME))
    # config_file_abs_path_to_skip 是脚本目录下的 config.ini，通常不会在 input_folder 的扫描中遇到
    # 但为了以防万一（如果脚本在 input_folder 中运行），我们不在这里特别处理它，
    # 因为 os.walk(input_folder) 不会扫描到脚本目录（除非它们是同一个）

    for current_dir_path, subdirectories, files_in_dir in os.walk(input_folder, topdown=True):
        abs_current_dir_path = os.path.abspath(current_dir_path)

        if abs_current_dir_path == new_output_dir_to_skip_abs:
            subdirectories[:] = [] 
            continue 

        files_to_scan = list(files_in_dir)
        # 日志文件只在 input_folder 的根目录被跳过
        if abs_current_dir_path == os.path.abspath(input_folder):
            if log_filename_val in files_to_scan: files_to_scan.remove(log_filename_val)
            # config.ini 不再从这里跳过，因为它与脚本同级

        for filename in files_to_scan:
            if filename.lower().endswith(supported_formats):
                all_files_to_process.append(os.path.join(current_dir_path, filename))
    return all_files_to_process

def calculate_target_output_dir(img_path, config):
    """计算给定图片在新结构下的最终输出目录路径"""
    input_folder_root = config['input_folder_root']
    base_new_output_root = os.path.join(input_folder_root, NEW_ROOT_OUTPUT_SUBFOLDER_NAME)

    original_image_parent_dir = os.path.dirname(img_path)
    relative_dir_from_input = os.path.relpath(original_image_parent_dir, input_folder_root)

    if relative_dir_from_input == '.': 
        return base_new_output_root 
    else:
        return os.path.join(base_new_output_root, relative_dir_from_input)

def check_if_already_processed(img_path, cfg):
    if cfg['overwrite_existing'] or cfg['is_dry_run']: return False
    mirrored_target_dir = calculate_target_output_dir(img_path, cfg)
    if not os.path.isdir(mirrored_target_dir): return False

    original_filename = os.path.basename(img_path)
    base, original_ext_str = os.path.splitext(original_filename)
    original_ext_lower = original_ext_str.lower()
    _, final_output_ext = get_dynamic_output_format_and_ext(original_ext_lower, cfg)

    is_split_candidate = False
    try:
        with Image.open(img_path) as temp_img:
            temp_img.load()
            original_width, original_height = temp_img.size
            sim_width, sim_height = original_width, original_height
            if cfg['resize_mode'] != 'none':
                if cfg['resize_mode'] == 'fixed_height' and cfg['target_height'] > 0 and original_height != cfg['target_height']:
                    ratio = cfg['target_height'] / float(original_height); sim_width = int(original_width * ratio); sim_height = cfg['target_height']
                elif cfg['resize_mode'] == 'fixed_width' and cfg['target_width'] > 0 and original_width != cfg['target_width']:
                    ratio = cfg['target_width'] / float(original_width); sim_height = int(original_height * ratio); sim_width = cfg['target_width']
                elif cfg['resize_mode'] == 'fit_bounds':
                    if cfg['max_width'] > 0 and cfg['max_height'] > 0 and (original_width > cfg['max_width'] or original_height > cfg['max_height']):
                        ratio = min(cfg['max_width']/float(original_width), cfg['max_height']/float(original_height))
                        sim_width = int(original_width * ratio); sim_height = int(original_height * ratio)
            is_split_candidate = sim_height > 0 and sim_width > sim_height
    except (UnidentifiedImageError, FileNotFoundError, Exception): return False

    expected_outputs = []
    if cfg['enable_double_page_split'] and is_split_candidate:
        page1_savename = cfg['template_split_page1'].format(base=base, ext=final_output_ext, page_num=1)
        page2_savename = cfg['template_split_page2'].format(base=base, ext=final_output_ext, page_num=2)
        expected_outputs.extend([os.path.join(mirrored_target_dir, page1_savename), os.path.join(mirrored_target_dir, page2_savename)])
    else:
        single_savename = cfg['template_single'].format(base=base, ext=final_output_ext)
        expected_outputs.append(os.path.join(mirrored_target_dir, single_savename))
    try: source_mtime = os.path.getmtime(img_path)
    except FileNotFoundError: return False
    for out_file in expected_outputs:
        if not os.path.exists(out_file) or os.path.getmtime(out_file) < source_mtime: return False
    return True

def worker_process_image(img_path, config):
    filename = os.path.basename(img_path)
    original_base, original_ext_str = os.path.splitext(filename)
    original_ext_lower = original_ext_str.lower()
    final_save_format, final_output_ext = get_dynamic_output_format_and_ext(original_ext_lower, config)
    mirrored_target_dir = calculate_target_output_dir(img_path, config)

    try:
        img = Image.open(img_path)
        original_width, original_height = img.size
        img.load()
        if final_save_format == 'JPEG' and (img.mode == 'RGBA' or img.mode == 'LA' or (img.mode == 'P' and 'transparency' in img.info)):
            img = img.convert('RGB')
        elif final_save_format == 'PNG' and img.mode == 'P' and 'transparency' in img.info:
            img = img.convert('RGBA')

        resized_img = img
        new_width, new_height = original_width, original_height
        if config['resize_mode'] != 'none':
            if config['resize_mode'] == 'fixed_height' and config['target_height'] > 0 and original_height != config['target_height']:
                ratio = config['target_height'] / float(original_height); new_width = int(original_width * ratio); new_height = config['target_height']
            elif config['resize_mode'] == 'fixed_width' and config['target_width'] > 0 and original_width != config['target_width']:
                ratio = config['target_width'] / float(original_width); new_height = int(original_height * ratio); new_width = config['target_width']
            elif config['resize_mode'] == 'fit_bounds':
                if config['max_width'] > 0 and config['max_height'] > 0 and (original_width > config['max_width'] or original_height > config['max_height']):
                    ratio = min(config['max_width']/float(original_width), config['max_height']/float(original_height))
                    new_width = int(original_width * ratio); new_height = int(original_height * ratio)
            if new_width != original_width or new_height != original_height:
                try: resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                except AttributeError: resized_img = img.resize((new_width, new_height), Image.ANTIALIAS)
        
        current_width, current_height = resized_img.size
        is_split_action = False
        save_options = {}
        if final_save_format == 'JPEG': save_options['quality'] = config['jpeg_quality']

        if config['enable_double_page_split'] and current_height > 0 and current_width > current_height: # Split
            is_split_action = True; midpoint = current_width // 2
            page_left_data = resized_img.crop((0, 0, midpoint, current_height))
            page_right_data = resized_img.crop((midpoint, 0, current_width, current_height))
            page1_savename = config['template_split_page1'].format(base=original_base, ext=final_output_ext, page_num=1)
            page2_savename = config['template_split_page2'].format(base=original_base, ext=final_output_ext, page_num=2)
            save_path_p1 = os.path.join(mirrored_target_dir, page1_savename)
            save_path_p2 = os.path.join(mirrored_target_dir, page2_savename)
            if not config['is_dry_run']:
                if config['split_left_to_right']:
                    page_left_data.save(save_path_p1, format=final_save_format, **save_options)
                    page_right_data.save(save_path_p2, format=final_save_format, **save_options)
                else: 
                    page_right_data.save(save_path_p1, format=final_save_format, **save_options)
                    page_left_data.save(save_path_p2, format=final_save_format, **save_options)
        else: # No split
            save_filename = config['template_single'].format(base=original_base, ext=final_output_ext)
            save_path = os.path.join(mirrored_target_dir, save_filename)
            if not config['is_dry_run']:
                resized_img.save(save_path, format=final_save_format, **save_options)
        img.close()
        # 使用 input_folder_root 计算相对路径用于日志
        log_output_path = os.path.relpath(mirrored_target_dir, config['input_folder_root'])
        return "success", f"已处理: {filename} (输出到 {log_output_path}, 格式 {final_output_ext})", filename, is_split_action
    except FileNotFoundError: return "error", f"文件未找到: {filename}", filename, False
    except UnidentifiedImageError: return "error", f"无法识别图片格式: {filename}", filename, False
    except Exception as e: return "error", f"处理 '{filename}' 错误: {str(e)}", filename, False

def process_images_with_config(cfg, config_file_path_abs=None, *, additional_log_handlers=None, include_console_log=True):
    input_folder = cfg['input_folder_root']
    log_file_path = os.path.join(input_folder, cfg['log_filename'])
    setup_logging(log_file_path, cfg['is_dry_run'], additional_handlers=additional_log_handlers, include_console=include_console_log)

    logging.info("--- 开始处理 ---")
    if config_file_path_abs:
        logging.info(f"配置文件: {config_file_path_abs}")
    logging.info(f"输出镜像根目录: {os.path.join(input_folder, NEW_ROOT_OUTPUT_SUBFOLDER_NAME)}")

    supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp')
    logging.info("步骤1: 扫描所有图片文件...")
    all_image_paths_discovered = get_all_image_files(input_folder, supported_formats, cfg['log_filename'])
    if not all_image_paths_discovered:
        logging.info("未找到支持的图片文件。")
        logging.info("--- 处理结束 ---")
        return {
            'total_processed': 0,
            'total_split': 0,
            'skipped_due_to_cache': 0,
            'total_errors': 0,
            'total_discovered': 0,
            'total_to_process': 0,
            'log_file_path': log_file_path,
            'status': 'no_images'
        }
    logging.info(f"共发现 {len(all_image_paths_discovered)} 张潜在图片。")

    base_new_output_dir_root = os.path.join(input_folder, NEW_ROOT_OUTPUT_SUBFOLDER_NAME)

    if not cfg['is_dry_run'] and not os.path.exists(base_new_output_dir_root):
        try:
            os.makedirs(base_new_output_dir_root)
            logging.info(f"已创建总输出根目录: {base_new_output_dir_root}")
        except OSError as e:
            logging.error(f"错误：无法创建总输出根目录 '{base_new_output_dir_root}': {e}。处理中止。")
            return {
                'total_processed': 0,
                'total_split': 0,
                'skipped_due_to_cache': 0,
                'total_errors': 1,
                'total_discovered': len(all_image_paths_discovered),
                'total_to_process': 0,
                'log_file_path': log_file_path,
                'status': 'failed'
            }
    elif cfg['is_dry_run'] and not os.path.exists(base_new_output_dir_root):
        logging.info(f"[试运行] 将创建总输出根目录: {base_new_output_dir_root}")

    logging.info("步骤2: 准备镜像输出目录结构并筛选待处理图片...")
    tasks_to_process = []
    unique_original_parent_dirs = sorted(list(set(os.path.dirname(p) for p in all_image_paths_discovered)))

    for original_parent_dir in unique_original_parent_dirs:
        mirrored_target_dir = calculate_target_output_dir(os.path.join(original_parent_dir, "dummy.file"), cfg)

        if cfg['is_dry_run']:
            if not os.path.exists(mirrored_target_dir):
                logging.info(f"[试运行] 将创建镜像目标文件夹: {mirrored_target_dir}")
            elif cfg['overwrite_existing']:
                logging.info(f"[试运行] 镜像目标文件夹 '{mirrored_target_dir}' 中的内容将被覆盖。")
        else:
            if os.path.exists(mirrored_target_dir):
                if cfg['overwrite_existing']:
                    logging.info(f"镜像目标文件夹 '{mirrored_target_dir}' 已存在，将清空。")
                    try:
                        shutil.rmtree(mirrored_target_dir)
                        os.makedirs(mirrored_target_dir)
                    except OSError as e:
                        logging.error(f"错误：无法清空/创建镜像目标文件夹 '{mirrored_target_dir}': {e}。")
                        all_image_paths_discovered = [p for p in all_image_paths_discovered if os.path.dirname(p) != original_parent_dir]
                        continue
            else:
                try:
                    os.makedirs(mirrored_target_dir, exist_ok=True)
                except OSError as e:
                    logging.error(f"错误：无法创建镜像目标文件夹 '{mirrored_target_dir}': {e}。")
                    all_image_paths_discovered = [p for p in all_image_paths_discovered if os.path.dirname(p) != original_parent_dir]
                    continue

    skipped_due_to_cache = 0
    for img_path in all_image_paths_discovered:
        mirrored_target_dir = calculate_target_output_dir(img_path, cfg)
        if not cfg['is_dry_run'] and not os.path.isdir(mirrored_target_dir):
            continue
        if not cfg['overwrite_existing'] and check_if_already_processed(img_path, cfg):
            skipped_due_to_cache += 1
            continue
        tasks_to_process.append((img_path, cfg))

    if skipped_due_to_cache > 0:
        logging.info(f"智能跳过: {skipped_due_to_cache} 个文件因已处理且最新而被跳过。")
    if not tasks_to_process:
        logging.info("没有需要处理的图片任务。")
        logging.info("--- 处理结束 ---")
        return {
            'total_processed': 0,
            'total_split': 0,
            'skipped_due_to_cache': skipped_due_to_cache,
            'total_errors': 0,
            'total_discovered': len(all_image_paths_discovered),
            'total_to_process': 0,
            'log_file_path': log_file_path,
            'status': 'nothing_to_do'
        }

    logging.info(f"步骤3: 开始并行处理 {len(tasks_to_process)} 张图片...")
    total_processed_count = 0
    total_split_count = 0
    total_errors = 0
    try:
        with multiprocessing.Pool(processes=cfg['num_processes']) as pool:
            results = []
            with tqdm(total=len(tasks_to_process), desc="图片处理进度", unit="张") as pbar:
                for result in pool.imap_unordered(worker_process_image_wrapper, tasks_to_process):
                    results.append(result)
                    pbar.update(1)
        for status, message, _, is_split in results:
            if status == "success":
                total_processed_count += 1
                if is_split:
                    total_split_count += 1
                logging.info(message)
            elif status == "error":
                total_errors += 1
                logging.error(message)
    except Exception as e:
        logging.critical(f"多进程处理中发生严重错误: {e}", exc_info=True)
        total_errors = len(tasks_to_process)

    logging.info("\n--- 处理结束 ---")
    if cfg['is_dry_run']:
        logging.info("“试运行”模式结束。")
    logging.info(f"总共成功处理了 {total_processed_count} 张图片。")
    logging.info(f"其中 {total_split_count} 张图片被切割。")
    if skipped_due_to_cache > 0 and not cfg['overwrite_existing']:
        logging.info(f"{skipped_due_to_cache} 张图片因已处理且最新而被跳过。")
    if total_errors > 0:
        logging.warning(f"处理中发生 {total_errors} 个错误。请检查日志。")
    logging.info(f"详细日志已保存到: {log_file_path}")

    return {
        'total_processed': total_processed_count,
        'total_split': total_split_count,
        'skipped_due_to_cache': skipped_due_to_cache,
        'total_errors': total_errors,
        'total_discovered': len(all_image_paths_discovered),
        'total_to_process': len(tasks_to_process),
        'log_file_path': log_file_path,
        'status': 'completed'
    }


def process_manga_folder_recursive():
    input_folder = input("请输入漫画根文件夹的路径: ").strip()
    if not os.path.isdir(input_folder):
        print(f"错误：文件夹 '{input_folder}' 不存在。")
        return

    script_directory = get_script_directory()
    config_file_path_abs = os.path.join(script_directory, CONFIG_FILENAME) # config.ini 与脚本同级

    cfg = load_or_get_config(config_file_path_abs, input_folder) # 传递绝对配置文件路径

    process_images_with_config(cfg, config_file_path_abs=config_file_path_abs)

def worker_process_image_wrapper(args): return worker_process_image(*args)

if __name__ == "__main__":
    multiprocessing.freeze_support() 
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    try: process_manga_folder_recursive()
    except Exception as e: logging.critical(f"脚本发生未捕获的致命错误: {e}", exc_info=True); print(f"脚本因严重错误终止，请检查日志。")


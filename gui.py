import logging
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from run import (
    CONFIG_FILENAME,
    config_parser_to_dict,
    process_images_with_config,
    read_config_file,
    save_config_parser,
)


class TextWidgetLogHandler(logging.Handler):
    """将日志输出同步到 Tk 文本组件。"""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        message = self.format(record)
        self.text_widget.after(0, self._append, message)

    def _append(self, message):
        self.text_widget.configure(state='normal')
        self.text_widget.insert('end', message + '\n')
        self.text_widget.see('end')
        self.text_widget.configure(state='disabled')


class AutoComicRefinerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoComicRefiner 图形界面")
        self.geometry("900x720")
        self.minsize(880, 640)
        self._script_dir = os.path.dirname(os.path.abspath(__file__))
        self._config_path = os.path.join(self._script_dir, CONFIG_FILENAME)
        self.config_parser = read_config_file(self._config_path)
        self._last_custom_dimensions = {}
        self._preview_supported_formats = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.gif')
        self._preview_request_id = 0
        self._preview_image_tk = None
        self._preview_job = None
        self._preview_image_paths = []
        self._preview_current_index = None
        self._preview_folder = ''
        self._thumbnail_photo_images = []
        self._thumbnail_buttons = []
        self._thumbnail_default_bg = None
        self._thumbnail_default_active_bg = None
        self._current_preview_load_token = None
        self._create_variables()
        self._build_ui()
        self._load_config_to_fields()
        self.processing_thread = None
        self.log_handler = TextWidgetLogHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self.log_handler.setFormatter(formatter)
        self._update_resize_description()
        self._apply_dimension_mode(self.target_height_mode_var, self.target_height_entry, self.target_height_var, 'target_height')
        self._apply_dimension_mode(self.target_width_mode_var, self.target_width_entry, self.target_width_var, 'target_width')
        self._set_preview_message("请选择目录以查看预览。")
        self._sync_split_controls_state()
        self.bind('<Left>', lambda event: self._navigate_preview(-1))
        self.bind('<Right>', lambda event: self._navigate_preview(1))

    def _create_variables(self):
        self.input_folder_var = tk.StringVar()
        settings = self.config_parser['Settings']
        filenames = self.config_parser['Filenames']
        self.input_folder_var.trace_add('write', self._on_input_folder_change)
        self.dry_run_var = tk.BooleanVar(value=settings.getboolean('dry_run'))
        self.log_filename_var = tk.StringVar(value=settings.get('log_filename'))
        self.num_processes_var = tk.StringVar(value=settings.get('num_processes'))
        self.resize_mode_var = tk.StringVar(value=settings.get('resize_mode'))
        self.target_height_var = tk.StringVar(value=settings.get('target_height'))
        self.target_width_var = tk.StringVar(value=settings.get('target_width'))
        self.target_height_mode_var = tk.StringVar(value='自定义' if int(settings.get('target_height') or '0') > 0 else '不做处理')
        self.target_width_mode_var = tk.StringVar(value='自定义' if int(settings.get('target_width') or '0') > 0 else '不做处理')
        self.max_height_var = tk.StringVar(value=settings.get('max_height'))
        self.max_width_var = tk.StringVar(value=settings.get('max_width'))
        self.output_format_var = tk.StringVar(value=settings.get('output_format_for_others'))
        self.jpeg_quality_var = tk.StringVar(value=settings.get('jpeg_quality'))
        self.enable_split_var = tk.BooleanVar(value=settings.getboolean('enable_double_page_split'))
        self.split_left_to_right_var = tk.BooleanVar(value=settings.getboolean('split_order_is_left_to_right'))
        self.overwrite_existing_var = tk.BooleanVar(value=settings.getboolean('overwrite_existing_output_folders'))
        self.template_single_var = tk.StringVar(value=filenames.get('template_single'))
        self.template_split1_var = tk.StringVar(value=filenames.get('template_split_page1'))
        self.template_split2_var = tk.StringVar(value=filenames.get('template_split_page2'))
        self._last_custom_dimensions['target_height'] = self.target_height_var.get()
        self._last_custom_dimensions['target_width'] = self.target_width_var.get()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        main_frame = ttk.Frame(self, padding=20)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)

        # 输入路径
        ttk.Label(main_frame, text="漫画根目录:").grid(row=0, column=0, sticky="w")
        input_frame = ttk.Frame(main_frame)
        input_frame.grid(row=0, column=1, sticky="ew", pady=5)
        input_frame.columnconfigure(0, weight=1)
        ttk.Entry(input_frame, textvariable=self.input_folder_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(input_frame, text="浏览...", command=self._select_input_folder).grid(row=0, column=1, padx=(8, 0))

        # 设置面板
        settings_labelframe = ttk.LabelFrame(main_frame, text="处理设置", padding=15)
        settings_labelframe.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(15, 0))
        for i in range(4):
            settings_labelframe.columnconfigure(i, weight=1)

        ttk.Label(settings_labelframe, text="调整模式").grid(row=0, column=0, sticky="w")
        resize_combo = ttk.Combobox(settings_labelframe, textvariable=self.resize_mode_var,
                                     values=('fixed_height', 'fixed_width', 'fit_bounds', 'none'), state='readonly')
        resize_combo.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        resize_combo.bind('<<ComboboxSelected>>', self._update_resize_description)

        self.resize_mode_descriptions = {
            'fixed_height': '固定目标高度，宽度按比例缩放，适用于统一高度的竖排页面。',
            'fixed_width': '固定目标宽度，高度按比例缩放，适用于统一宽度的横向页面。',
            'fit_bounds': '限制图片在最大宽高范围内，超出时按比例缩小到指定边界。',
            'none': '不调整尺寸，保持原始分辨率。',
        }
        self.resize_description_label = ttk.Label(
            settings_labelframe,
            text="",
            foreground="#555",
            justify="left",
            wraplength=520,
        )
        self.resize_description_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 4))

        ttk.Checkbutton(settings_labelframe, text="试运行 (不写入文件)", variable=self.dry_run_var).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(settings_labelframe, text="覆盖已有输出", variable=self.overwrite_existing_var).grid(row=0, column=3, sticky="w")

        ttk.Label(settings_labelframe, text="目标高度").grid(row=2, column=0, sticky="w", pady=(6, 0))
        target_height_frame = ttk.Frame(settings_labelframe)
        target_height_frame.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        target_height_frame.columnconfigure(0, weight=1)
        self.target_height_entry = ttk.Entry(target_height_frame, textvariable=self.target_height_var)
        self.target_height_entry.grid(row=0, column=0, sticky="ew")
        self.target_height_mode_combo = ttk.Combobox(
            target_height_frame,
            textvariable=self.target_height_mode_var,
            values=('自定义', '不做处理'),
            state='readonly',
            width=10,
        )
        self.target_height_mode_combo.grid(row=0, column=1, padx=(8, 0))
        self.target_height_mode_combo.bind('<<ComboboxSelected>>',
                                           lambda _event: self._apply_dimension_mode(self.target_height_mode_var, self.target_height_entry, self.target_height_var, 'target_height'))

        ttk.Label(settings_labelframe, text="目标宽度").grid(row=2, column=2, sticky="w", pady=(6, 0))
        target_width_frame = ttk.Frame(settings_labelframe)
        target_width_frame.grid(row=2, column=3, sticky="ew", pady=(6, 0))
        target_width_frame.columnconfigure(0, weight=1)
        self.target_width_entry = ttk.Entry(target_width_frame, textvariable=self.target_width_var)
        self.target_width_entry.grid(row=0, column=0, sticky="ew")
        self.target_width_mode_combo = ttk.Combobox(
            target_width_frame,
            textvariable=self.target_width_mode_var,
            values=('自定义', '不做处理'),
            state='readonly',
            width=10,
        )
        self.target_width_mode_combo.grid(row=0, column=1, padx=(8, 0))
        self.target_width_mode_combo.bind('<<ComboboxSelected>>',
                                          lambda _event: self._apply_dimension_mode(self.target_width_mode_var, self.target_width_entry, self.target_width_var, 'target_width'))

        ttk.Label(settings_labelframe, text="最大高度").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(settings_labelframe, textvariable=self.max_height_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))
        ttk.Label(settings_labelframe, text="最大宽度").grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(settings_labelframe, textvariable=self.max_width_var).grid(row=3, column=3, sticky="ew", pady=(6, 0))

        ttk.Label(settings_labelframe, text="输出格式 (其他)").grid(row=4, column=0, sticky="w", pady=(6, 0))
        format_combo = ttk.Combobox(settings_labelframe, textvariable=self.output_format_var,
                                    values=('jpeg', 'png'), state='readonly')
        format_combo.grid(row=4, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(settings_labelframe, text="JPEG 质量").grid(row=4, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(settings_labelframe, textvariable=self.jpeg_quality_var).grid(row=4, column=3, sticky="ew", pady=(6, 0))

        ttk.Label(settings_labelframe, text="并行进程数").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(settings_labelframe, textvariable=self.num_processes_var).grid(row=5, column=1, sticky="ew", pady=(6, 0))
        split_frame = ttk.Frame(settings_labelframe)
        split_frame.grid(row=5, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.enable_split_check = ttk.Checkbutton(split_frame, text="启用双页切割", variable=self.enable_split_var, command=self._sync_split_controls_state)
        self.enable_split_check.grid(row=0, column=0, sticky="w")
        self.split_order_frame = ttk.Frame(split_frame)
        self.split_order_frame.grid(row=0, column=1, padx=(12, 0))
        self.split_order_ltr = ttk.Radiobutton(self.split_order_frame, text="从左向右", variable=self.split_left_to_right_var, value=True)
        self.split_order_ltr.grid(row=0, column=0, sticky="w")
        self.split_order_rtl = ttk.Radiobutton(self.split_order_frame, text="从右向左", variable=self.split_left_to_right_var, value=False)
        self.split_order_rtl.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Label(settings_labelframe, text="日志文件名").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(settings_labelframe, textvariable=self.log_filename_var).grid(row=6, column=1, columnspan=3, sticky="ew", pady=(6, 0))

        # 文件名模板
        template_labelframe = ttk.LabelFrame(main_frame, text="文件名模板", padding=15)
        template_labelframe.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(15, 0))
        template_labelframe.columnconfigure(1, weight=1)

        ttk.Label(template_labelframe, text="单页模板").grid(row=0, column=0, sticky="w")
        ttk.Entry(template_labelframe, textvariable=self.template_single_var).grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(template_labelframe, text="切割第一页模板").grid(row=1, column=0, sticky="w")
        ttk.Entry(template_labelframe, textvariable=self.template_split1_var).grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(template_labelframe, text="切割第二页模板").grid(row=2, column=0, sticky="w")
        ttk.Entry(template_labelframe, textvariable=self.template_split2_var).grid(row=2, column=1, sticky="ew", pady=5)

        # 预览窗格
        preview_frame = ttk.LabelFrame(main_frame, text="目录预览", padding=15)
        preview_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(15, 0))
        preview_frame.columnconfigure(0, weight=0)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(2, weight=1)
        self.preview_image_label = ttk.Label(preview_frame, anchor="center", width=36)
        self.preview_image_label.grid(row=0, column=0, sticky="n")
        self.preview_info_var = tk.StringVar(value="")
        self.preview_info_label = ttk.Label(preview_frame, textvariable=self.preview_info_var, justify="left", wraplength=360)
        self.preview_info_label.grid(row=0, column=1, sticky="nw", padx=(18, 0))
        nav_frame = ttk.Frame(preview_frame)
        nav_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        nav_frame.columnconfigure(1, weight=1)
        self.prev_button = ttk.Button(nav_frame, text="上一张", command=lambda: self._navigate_preview(-1))
        self.prev_button.grid(row=0, column=0, sticky="w")
        self.preview_index_var = tk.StringVar(value="未加载")
        ttk.Label(nav_frame, textvariable=self.preview_index_var).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.next_button = ttk.Button(nav_frame, text="下一张", command=lambda: self._navigate_preview(1))
        self.next_button.grid(row=0, column=2, sticky="e")
        self.thumbnail_canvas = tk.Canvas(preview_frame, height=130, highlightthickness=0)
        self.thumbnail_canvas.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        self.thumbnail_scrollbar = ttk.Scrollbar(preview_frame, orient='horizontal', command=self.thumbnail_canvas.xview)
        self.thumbnail_scrollbar.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.thumbnail_canvas.configure(xscrollcommand=self.thumbnail_scrollbar.set)
        self.thumbnail_inner_frame = ttk.Frame(self.thumbnail_canvas)
        self.thumbnail_canvas_window = self.thumbnail_canvas.create_window((0, 0), window=self.thumbnail_inner_frame, anchor='nw')
        self.thumbnail_inner_frame.bind(
            '<Configure>',
            lambda _event: self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox('all')),
        )

        # 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(15, 0))
        button_frame.columnconfigure(2, weight=1)
        ttk.Button(button_frame, text="保存配置", command=self._save_config).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(button_frame, text="清空日志", command=self._clear_log).grid(row=0, column=1, padx=(0, 10))
        self.start_button = ttk.Button(button_frame, text="开始处理", command=self._start_processing)
        self.start_button.grid(row=0, column=2, sticky="e")

        # 日志输出
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding=10)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(15, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap='word', state='disabled', height=12)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _select_input_folder(self):
        selected = filedialog.askdirectory(title="选择漫画根目录")
        if selected:
            self.input_folder_var.set(selected)
            self._load_preview_for_folder(selected)

    def _load_config_to_fields(self):
        # 已在变量初始化时同步
        pass

    def _clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def _on_input_folder_change(self, *_args):
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
            self._preview_job = None
        folder = self.input_folder_var.get().strip()
        if not folder:
            self._set_preview_message("请选择目录以查看预览。")
            return
        self._preview_job = self.after(600, lambda: self._load_preview_for_folder(folder))

    def _apply_dimension_mode(self, mode_var, entry_widget, value_var, key):
        mode = mode_var.get()
        current_value = value_var.get().strip()
        if mode == '不做处理':
            if current_value and current_value not in ('0',):
                self._last_custom_dimensions[key] = current_value
            value_var.set('0')
            entry_widget.configure(state='disabled')
        else:
            entry_widget.configure(state='normal')
            if current_value in ('0', ''):
                restore_val = self._last_custom_dimensions.get(key, '')
                value_var.set(restore_val)

    def _sync_split_controls_state(self):
        if not hasattr(self, 'split_order_ltr'):
            return
        if self.enable_split_var.get():
            self.split_order_ltr.state(['!disabled'])
            self.split_order_rtl.state(['!disabled'])
        else:
            self.split_order_ltr.state(['disabled'])
            self.split_order_rtl.state(['disabled'])

    def _update_parser_from_fields(self):
        try:
            num_processes = int(self.num_processes_var.get())
            if num_processes < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("无效的输入", "并行进程数必须为正整数。")
            return False

        if self.target_height_mode_var.get() == '自定义' and not self.target_height_var.get().strip():
            messagebox.showerror("无效的输入", "目标高度选择自定义时需要填写数值。")
            return False
        if self.target_width_mode_var.get() == '自定义' and not self.target_width_var.get().strip():
            messagebox.showerror("无效的输入", "目标宽度选择自定义时需要填写数值。")
            return False

        if self.target_height_mode_var.get() == '不做处理':
            self.target_height_var.set('0')
        if self.target_width_mode_var.get() == '不做处理':
            self.target_width_var.set('0')

        int_fields = {
            'target_height': self.target_height_var,
            'target_width': self.target_width_var,
            'max_height': self.max_height_var,
            'max_width': self.max_width_var,
            'jpeg_quality': self.jpeg_quality_var,
        }
        for field_name, var in int_fields.items():
            value = var.get().strip()
            if not value:
                value = '0'
            try:
                numeric_value = int(value)
            except ValueError:
                messagebox.showerror("无效的输入", f"字段 {field_name} 需要整数。")
                return False
            if field_name == 'jpeg_quality' and not (1 <= numeric_value <= 100):
                messagebox.showerror("无效的输入", "JPEG 质量必须在 1-100 之间。")
                return False
            self.config_parser['Settings'][field_name] = value

        self.config_parser['Settings']['num_processes'] = str(num_processes)
        self.config_parser['Settings']['resize_mode'] = self.resize_mode_var.get()
        self.config_parser['Settings']['dry_run'] = 'true' if self.dry_run_var.get() else 'false'
        self.config_parser['Settings']['output_format_for_others'] = self.output_format_var.get()
        self.config_parser['Settings']['enable_double_page_split'] = 'true' if self.enable_split_var.get() else 'false'
        self.config_parser['Settings']['split_order_is_left_to_right'] = 'true' if self.split_left_to_right_var.get() else 'false'
        self.config_parser['Settings']['overwrite_existing_output_folders'] = 'true' if self.overwrite_existing_var.get() else 'false'

        log_filename = self.log_filename_var.get().strip() or self.config_parser['Settings']['log_filename']
        self.config_parser['Settings']['log_filename'] = log_filename

        self.config_parser['Filenames']['template_single'] = self.template_single_var.get().strip() or '{base}{ext}'
        self.config_parser['Filenames']['template_split_page1'] = self.template_split1_var.get().strip() or '{base}_p1{ext}'
        self.config_parser['Filenames']['template_split_page2'] = self.template_split2_var.get().strip() or '{base}_p2{ext}'
        return True

    def _save_config(self):
        if not self._update_parser_from_fields():
            return
        try:
            save_config_parser(self.config_parser, self._config_path)
            messagebox.showinfo("配置已保存", f"已写入 {self._config_path}")
        except OSError as exc:
            messagebox.showerror("保存失败", f"无法写入配置文件: {exc}")

    def _start_processing(self):
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("处理中", "当前仍在处理，请稍后。")
            return

        input_folder = self.input_folder_var.get().strip()
        if not input_folder:
            messagebox.showerror("缺少输入", "请先选择漫画根目录。")
            return
        if not os.path.isdir(input_folder):
            messagebox.showerror("路径无效", "指定的漫画根目录不存在。")
            return

        if not self._update_parser_from_fields():
            return

        self._clear_log()
        self.start_button.configure(state='disabled')

        cfg_dict = config_parser_to_dict(self.config_parser, input_folder)

        def run_processing():
            try:
                summary = process_images_with_config(
                    cfg_dict,
                    config_file_path_abs=self._config_path,
                    additional_log_handlers=[self.log_handler],
                    include_console_log=False,
                )
                self.log_text.after(0, self._on_processing_complete, summary)
            except Exception as exc:
                self.log_text.after(0, self._on_processing_failed, exc)

        self.processing_thread = threading.Thread(target=run_processing, daemon=True)
        self.processing_thread.start()

    def _on_processing_complete(self, summary):
        self.start_button.configure(state='normal')
        status_map = {
            'completed': "处理完成",
            'no_images': "未找到图片",
            'nothing_to_do': "无需处理",
            'failed': "执行失败",
        }
        status = status_map.get(summary.get('status', 'completed'), summary.get('status', 'completed'))
        details = [
            f"处理状态: {status}",
            f"扫描总数: {summary.get('total_discovered', 0)}",
            f"实际处理: {summary.get('total_processed', 0)}",
            f"切割页数: {summary.get('total_split', 0)}",
            f"跳过 (缓存): {summary.get('skipped_due_to_cache', 0)}",
            f"错误数: {summary.get('total_errors', 0)}",
            f"日志文件: {summary.get('log_file_path', '未知')}",
        ]
        messagebox.showinfo("处理结果", "\n".join(details))

    def _on_processing_failed(self, exc):
        self.start_button.configure(state='normal')
        messagebox.showerror("处理失败", f"发生错误: {exc}")

    def _update_resize_description(self, *_event):
        desc = self.resize_mode_descriptions.get(self.resize_mode_var.get(), '')
        self.resize_description_label.configure(text=desc)

    def _set_preview_message(self, message):
        self._preview_image_tk = None
        self.preview_image_label.configure(image='', text="暂无预览")
        self.preview_info_var.set(message)
        self.preview_index_var.set(message)
        self._preview_image_paths = []
        self._preview_current_index = None
        self._preview_folder = ''
        self._thumbnail_photo_images = []
        self._thumbnail_buttons = []
        self._thumbnail_default_bg = None
        self._thumbnail_default_active_bg = None
        for child in self.thumbnail_inner_frame.winfo_children():
            child.destroy()
        self.thumbnail_canvas.configure(scrollregion=(0, 0, 0, 0))
        self._update_navigation_controls()

    def _load_preview_for_folder(self, folder):
        if not folder or not os.path.isdir(folder):
            self._set_preview_message("目录不存在或不可访问。")
            return

        request_id = time.time()
        self._preview_request_id = request_id
        self._set_preview_message("正在扫描目录…")

        def worker():
            image_paths = self._find_all_images(folder)
            if self._preview_request_id != request_id:
                return
            if not image_paths:
                self.after(0, lambda: self._set_preview_message("未找到可预览的图片文件。"))
                return
            self.after(0, lambda: self._apply_preview_image_list(folder, image_paths, request_id))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_preview_image_list(self, folder, image_paths, request_id):
        if self._preview_request_id != request_id:
            return
        self._preview_folder = folder
        self._preview_image_paths = image_paths
        self._preview_current_index = 0
        self.preview_index_var.set(f"1 / {len(image_paths)}")
        for child in self.thumbnail_inner_frame.winfo_children():
            child.destroy()
        self._thumbnail_photo_images = [None] * len(image_paths)
        self._thumbnail_buttons = []
        self._thumbnail_default_bg = None
        self._thumbnail_default_active_bg = None
        for idx, path in enumerate(image_paths):
            btn = tk.Button(
                self.thumbnail_inner_frame,
                text=os.path.basename(path),
                width=14,
                height=6,
                wraplength=100,
                justify='center',
                command=lambda i=idx: self._on_thumbnail_selected(i),
            )
            btn.grid(row=0, column=idx, padx=4, pady=4, sticky='n')
            btn.configure(compound='top')
            if self._thumbnail_default_bg is None:
                self._thumbnail_default_bg = btn.cget('bg')
                self._thumbnail_default_active_bg = btn.cget('activebackground')
            self._thumbnail_buttons.append(btn)
        self.thumbnail_inner_frame.update_idletasks()
        self._update_navigation_controls()
        self._start_thumbnail_loader(image_paths, request_id)
        self._load_preview_image(request_id, 0)

    def _start_thumbnail_loader(self, image_paths, request_id):
        def worker():
            for idx, path in enumerate(image_paths):
                if self._preview_request_id != request_id:
                    return
                try:
                    with Image.open(path) as thumb_img:
                        thumb_img.load()
                        thumb_copy = thumb_img.copy()
                except Exception:
                    thumb_copy = None

                if thumb_copy is not None:
                    thumb_copy.thumbnail((96, 96))
                    photo = ImageTk.PhotoImage(thumb_copy)
                else:
                    photo = None

                def apply(idx=idx, photo=photo):
                    if self._preview_request_id != request_id or idx >= len(self._thumbnail_buttons):
                        return
                    button = self._thumbnail_buttons[idx]
                    if photo is not None:
                        self._thumbnail_photo_images[idx] = photo
                        button.configure(image=photo)
                    else:
                        button.configure(text=os.path.basename(image_paths[idx]))

                self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _load_preview_image(self, request_id, index):
        if self._preview_request_id != request_id:
            return
        if index < 0 or index >= len(self._preview_image_paths):
            return
        image_path = self._preview_image_paths[index]
        load_token = (request_id, index, time.time())
        self._current_preview_load_token = load_token
        self.preview_image_label.configure(image='', text="加载中…")
        self.preview_info_var.set("正在加载预览…")

        def worker():
            try:
                with Image.open(image_path) as img:
                    img.load()
                    info_text = self._build_preview_info(self._preview_folder, image_path, img, original_format=img.format)
                    display_img = img.copy()
            except Exception as exc:  # pragma: no cover - 仅在 GUI 运行时触发
                self.after(0, lambda exc=exc: self._handle_preview_error(load_token, exc))
                return

            display_img.thumbnail((360, 360))
            photo = ImageTk.PhotoImage(display_img)

            def apply_preview():
                if self._current_preview_load_token != load_token:
                    return
                self._preview_image_tk = photo
                self.preview_image_label.configure(image=photo, text="")
                self.preview_info_var.set(info_text)
                self._preview_current_index = index
                self.preview_index_var.set(f"{index + 1} / {len(self._preview_image_paths)}")
                self._highlight_thumbnail(index)
                self._update_navigation_controls()

            self.after(0, apply_preview)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_preview_error(self, load_token, exc):
        if self._current_preview_load_token != load_token:
            return
        self.preview_image_label.configure(image='', text="暂无预览")
        self.preview_info_var.set(f"加载预览失败: {exc}")
        self._preview_image_tk = None

    def _navigate_preview(self, step):
        if not self._preview_image_paths:
            return
        current = self._preview_current_index if self._preview_current_index is not None else 0
        self._navigate_to_index(current + step)

    def _navigate_to_index(self, index):
        if not self._preview_image_paths:
            return
        index = max(0, min(index, len(self._preview_image_paths) - 1))
        if self._preview_current_index == index and self._preview_image_tk is not None:
            return
        self.preview_index_var.set(f"{index + 1} / {len(self._preview_image_paths)}")
        self._highlight_thumbnail(index)
        self._update_navigation_controls()
        self._load_preview_image(self._preview_request_id, index)

    def _on_thumbnail_selected(self, index):
        self._navigate_to_index(index)

    def _highlight_thumbnail(self, index):
        for idx, button in enumerate(self._thumbnail_buttons):
            if button is None:
                continue
            if idx == index:
                button.configure(relief='sunken', bg='#dbe9ff', activebackground='#dbe9ff')
            else:
                default_bg = self._thumbnail_default_bg or button.cget('bg')
                default_active = self._thumbnail_default_active_bg or button.cget('activebackground')
                button.configure(relief='raised', bg=default_bg, activebackground=default_active)

    def _update_navigation_controls(self):
        has_images = bool(self._preview_image_paths)
        if has_images:
            current = self._preview_current_index if self._preview_current_index is not None else 0
            if current <= 0:
                self.prev_button.state(['disabled'])
            else:
                self.prev_button.state(['!disabled'])
            if current >= len(self._preview_image_paths) - 1:
                self.next_button.state(['disabled'])
            else:
                self.next_button.state(['!disabled'])
        else:
            self.prev_button.state(['disabled'])
            self.next_button.state(['disabled'])

    def _find_all_images(self, folder):
        image_paths = []
        for root_dir, dirs, files in os.walk(folder):
            dirs.sort()
            for filename in sorted(files):
                if filename.lower().endswith(self._preview_supported_formats):
                    image_paths.append(os.path.join(root_dir, filename))
        return image_paths

    def _build_preview_info(self, folder, image_path, image_obj, *, original_format=None):
        rel_path = os.path.relpath(image_path, folder)
        try:
            file_size = os.path.getsize(image_path)
            size_text = f"{file_size / 1024:.1f} KB"
        except OSError:
            size_text = "未知"

        mode = image_obj.mode
        channels = image_obj.getbands()
        bits_per_channel = self._estimate_bits_per_channel(mode)
        if bits_per_channel:
            depth_text = f"{bits_per_channel}-bit × {len(channels)} 通道"
        else:
            depth_text = f"未知 (模式 {mode})"

        dpi = image_obj.info.get('dpi') if hasattr(image_obj, 'info') else None
        if dpi and isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
            dpi_text = f"{dpi[0]:.0f} × {dpi[1]:.0f} dpi"
        else:
            dpi_text = "未标注"

        info_lines = [
            f"文件: {rel_path}",
            f"格式: {original_format or os.path.splitext(image_path)[1].lstrip('.').upper()}",
            f"分辨率: {image_obj.width} × {image_obj.height}",
            f"色彩模式: {mode} ({', '.join(channels)})",
            f"色深: {depth_text}",
            f"DPI: {dpi_text}",
            f"文件大小: {size_text}",
        ]
        return "\n".join(info_lines)

    @staticmethod
    def _estimate_bits_per_channel(mode):
        mapping = {
            '1': 1,
            'L': 8,
            'P': 8,
            'RGB': 8,
            'RGBA': 8,
            'CMYK': 8,
            'YCbCr': 8,
            'I;16': 16,
            'I;16B': 16,
            'I;16L': 16,
            'I;16S': 16,
            'I;32': 32,
            'I': 32,
            'F': 32,
        }
        return mapping.get(mode)


def main():
    multiprocessing_support()
    app = AutoComicRefinerApp()
    app.mainloop()


def multiprocessing_support():
    try:
        import multiprocessing

        multiprocessing.freeze_support()
    except Exception:
        pass


if __name__ == "__main__":
    main()

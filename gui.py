import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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
        self._create_variables()
        self._build_ui()
        self._load_config_to_fields()
        self.processing_thread = None
        self.log_handler = TextWidgetLogHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self.log_handler.setFormatter(formatter)

    def _create_variables(self):
        self.input_folder_var = tk.StringVar()
        settings = self.config_parser['Settings']
        filenames = self.config_parser['Filenames']
        self.dry_run_var = tk.BooleanVar(value=settings.getboolean('dry_run'))
        self.log_filename_var = tk.StringVar(value=settings.get('log_filename'))
        self.num_processes_var = tk.StringVar(value=settings.get('num_processes'))
        self.resize_mode_var = tk.StringVar(value=settings.get('resize_mode'))
        self.target_height_var = tk.StringVar(value=settings.get('target_height'))
        self.target_width_var = tk.StringVar(value=settings.get('target_width'))
        self.max_height_var = tk.StringVar(value=settings.get('max_height'))
        self.max_width_var = tk.StringVar(value=settings.get('max_width'))
        self.output_format_var = tk.StringVar(value=settings.get('output_format_for_others'))
        self.jpeg_quality_var = tk.StringVar(value=settings.get('jpeg_quality'))
        self.split_left_to_right_var = tk.BooleanVar(value=settings.getboolean('split_order_is_left_to_right'))
        self.overwrite_existing_var = tk.BooleanVar(value=settings.getboolean('overwrite_existing_output_folders'))
        self.template_single_var = tk.StringVar(value=filenames.get('template_single'))
        self.template_split1_var = tk.StringVar(value=filenames.get('template_split_page1'))
        self.template_split2_var = tk.StringVar(value=filenames.get('template_split_page2'))

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

        ttk.Checkbutton(settings_labelframe, text="试运行 (不写入文件)", variable=self.dry_run_var).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(settings_labelframe, text="覆盖已有输出", variable=self.overwrite_existing_var).grid(row=0, column=3, sticky="w")

        ttk.Label(settings_labelframe, text="目标高度").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.target_height_var).grid(row=1, column=1, sticky="ew", pady=(10, 0))
        ttk.Label(settings_labelframe, text="目标宽度").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.target_width_var).grid(row=1, column=3, sticky="ew", pady=(10, 0))

        ttk.Label(settings_labelframe, text="最大高度").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.max_height_var).grid(row=2, column=1, sticky="ew", pady=(10, 0))
        ttk.Label(settings_labelframe, text="最大宽度").grid(row=2, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.max_width_var).grid(row=2, column=3, sticky="ew", pady=(10, 0))

        ttk.Label(settings_labelframe, text="输出格式 (其他)").grid(row=3, column=0, sticky="w", pady=(10, 0))
        format_combo = ttk.Combobox(settings_labelframe, textvariable=self.output_format_var,
                                    values=('jpeg', 'png'), state='readonly')
        format_combo.grid(row=3, column=1, sticky="ew", pady=(10, 0))

        ttk.Label(settings_labelframe, text="JPEG 质量").grid(row=3, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.jpeg_quality_var).grid(row=3, column=3, sticky="ew", pady=(10, 0))

        ttk.Label(settings_labelframe, text="并行进程数").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.num_processes_var).grid(row=4, column=1, sticky="ew", pady=(10, 0))

        ttk.Checkbutton(settings_labelframe, text="双页切割顺序: 左→右", variable=self.split_left_to_right_var).grid(row=4, column=2, sticky="w", pady=(10, 0))

        ttk.Label(settings_labelframe, text="日志文件名").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(settings_labelframe, textvariable=self.log_filename_var).grid(row=5, column=1, columnspan=3, sticky="ew", pady=(10, 0))

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

        # 操作按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(15, 0))
        button_frame.columnconfigure(2, weight=1)
        ttk.Button(button_frame, text="保存配置", command=self._save_config).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(button_frame, text="清空日志", command=self._clear_log).grid(row=0, column=1, padx=(0, 10))
        self.start_button = ttk.Button(button_frame, text="开始处理", command=self._start_processing)
        self.start_button.grid(row=0, column=2, sticky="e")

        # 日志输出
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding=10)
        log_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(15, 0))
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

    def _load_config_to_fields(self):
        # 已在变量初始化时同步
        pass

    def _clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def _update_parser_from_fields(self):
        try:
            num_processes = int(self.num_processes_var.get())
            if num_processes < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("无效的输入", "并行进程数必须为正整数。")
            return False

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

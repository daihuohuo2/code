# -*- coding: utf-8 -*-
import sys
import os
import configparser
import threading
import time
from datetime import datetime
try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False
    print("[Warning] pyserial 未安装，串口功能不可用。请执行: pip install pyserial")
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer, QObject, QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from CamOperation_class import CameraOperation
from MvCameraControl_class import *
from MvErrorDefine_const import *
from CameraParams_header import *
from PyUICBasicDemo import Ui_MainWindow
import ctypes


# 获取选取设备信息的索引，通过[]之间的字符去解析
def TxtWrapBy(start_str, end, all):
    start = all.find(start_str)
    if start >= 0:
        start += len(start_str)
        end = all.find(end, start)
        if end >= 0:
            return all[start:end].strip()


# 将返回的错误码转换为十六进制显示
def ToHexStr(num):
    chaDic = {10: 'a', 11: 'b', 12: 'c', 13: 'd', 14: 'e', 15: 'f'}
    hexStr = ""
    if num < 0:
        num = num + 2 ** 32
    while num >= 16:
        digit = num % 16
        hexStr = chaDic.get(digit, str(digit)) + hexStr
        num //= 16
    hexStr = chaDic.get(num, str(num)) + hexStr
    return hexStr


# ──────────────────────────────────────────────────────────────────
#  比例尺叠加层（透明子 Widget，覆盖在 widgetDisplay 正上方）
# ──────────────────────────────────────────────────────────────────
class ScaleBarOverlay(QWidget):
    """透明比例尺叠加层，绘制在相机预览区右上方。"""

    # 候选比例尺长度（mm）
    NICE_LENGTHS_MM = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                       1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(parent_widget.rect())
        self._pixels_per_mm = 100.0   # 相机图像像素/mm（标定值）
        self._img_width = 0            # 相机采集图像宽度（0 = 未知）
        self._bar_visible = False
        self.raise_()

    def set_pixels_per_mm(self, value):
        self._pixels_per_mm = max(value, 0.001)
        self.update()

    def set_img_width(self, w):
        self._img_width = w
        self.update()

    def set_visible(self, visible):
        self._bar_visible = visible
        self.update()

    def update_size(self):
        """跟随父控件尺寸调整自身大小。"""
        self.setGeometry(self.parentWidget().rect())
        self.update()

    def paintEvent(self, event):
        if not self._bar_visible or self._pixels_per_mm <= 0:
            return

        display_w = self.width()
        display_h = self.height()
        if display_w <= 0 or display_h <= 0:
            return

        # 计算显示像素/mm（考虑图像缩放比例）
        if self._img_width > 0:
            scale_factor = display_w / self._img_width
        else:
            scale_factor = 1.0
        display_ppmm = self._pixels_per_mm * scale_factor

        # 选取使比例尺约占显示宽度 20% 的最大"美观"长度
        target_px = display_w * 0.20
        bar_len_mm = self.NICE_LENGTHS_MM[0]
        bar_len_px = bar_len_mm * display_ppmm
        for L in self.NICE_LENGTHS_MM:
            px = L * display_ppmm
            if px > target_px:
                break
            bar_len_mm = L
            bar_len_px = px
        bar_len_px = max(bar_len_px, 4)

        # 格式化标签
        if bar_len_mm >= 1.0:
            label = "{:.0f} mm".format(bar_len_mm) if bar_len_mm == int(bar_len_mm) else "{} mm".format(bar_len_mm)
        else:
            label = "{:.0f} µm".format(bar_len_mm * 1000)

        # 绘制位置（左下角留边距）
        margin = 16
        bar_h = 8
        x0 = margin
        y0 = display_h - margin - bar_h - 18  # 18 px 留给文字
        x1 = x0 + int(bar_len_px)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 黑色阴影底层（提升可读性）
        shadow_pen = QPen(QColor(0, 0, 0, 180))
        shadow_pen.setWidth(3)
        painter.setPen(shadow_pen)
        painter.drawLine(x0, y0 + bar_h, x1, y0 + bar_h)  # 底边阴影

        # 绘制白色刻度条
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRect(x0 - 2, y0 - 2, int(bar_len_px) + 4, bar_h + 4)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRect(x0, y0, int(bar_len_px), bar_h)

        # 两端刻度竖线
        tick_pen = QPen(QColor(255, 255, 255, 230), 2)
        painter.setPen(tick_pen)
        tick_h = bar_h + 4
        painter.drawLine(x0, y0 - 2, x0, y0 + tick_h)
        painter.drawLine(x1, y0 - 2, x1, y0 + tick_h)

        # 绘制标签文字
        font = QFont("Arial", 9, QFont.Bold)
        painter.setFont(font)
        # 黑色阴影
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(x0 + 1, y0 - 3, label)
        # 白色前景
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(x0, y0 - 4, label)
        painter.end()


class _ResizeFilter(QObject):
    """事件过滤器：监听 widgetDisplay 的 Resize 事件，同步更新叠加层尺寸。"""
    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._overlay.update_size()
        return False


# ──────────────────────────────────────────────────────────────────
#  三维重建 — 深度从焦点（Depth From Focus）点云重建对话框
# ──────────────────────────────────────────────────────────────────

def _get_mpl_font():
    """返回支持中文显示的 matplotlib FontProperties（可选）"""
    try:
        from matplotlib.font_manager import FontProperties
        for fname in ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Arial Unicode MS']:
            try:
                fp = FontProperties(family=fname)
                return fp
            except Exception:
                continue
        return FontProperties()
    except Exception:
        return None


class PointCloudReconDialog(QDialog):
    """
    三维重建对话框（深度从焦点算法）

    原理：
      1. 控制 Z 轴从起始位置步进扫描到结束位置
      2. 每步采集一帧，计算逐像素锐度（拉普拉斯平方）
      3. 聚合各 Z 层锐度栈，取每像素最大锐度对应 Z 值为深度
      4. 利用 pixels_per_mm 标定值将像素坐标转为物理坐标（mm）
      5. 生成点云 (X_mm, Y_mm, Z_mm, Intensity)，可视化并导出
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("三维重建 — 点云数据重建")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        self._running = False
        self._worker_thread = None
        self._depth_map = None
        self._point_cloud = None
        self._img_size = (0, 0)
        self._setup_ui()

    # ── UI 构建 ───────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 扫描参数 ──────────────────────────────────────────
        grp_scan = QGroupBox("扫描参数（Z 轴）")
        form_scan = QFormLayout()
        form_scan.setLabelAlignment(Qt.AlignRight)
        self.edtZStart = QLineEdit("-2.0")
        self.edtZEnd   = QLineEdit("2.0")
        self.edtZStep  = QLineEdit("0.1")
        self.edtDelay  = QLineEdit("0.15")
        self.edtZStart.setToolTip("Z 轴扫描起始位置（mm，绝对坐标）")
        self.edtZEnd  .setToolTip("Z 轴扫描结束位置（mm，绝对坐标）")
        self.edtZStep .setToolTip("每步移动量（mm），建议 0.05 ~ 0.5mm")
        self.edtDelay .setToolTip("每步移动后等待时间（秒），用于运动稳定")
        form_scan.addRow("Z 起始位置 (mm):", self.edtZStart)
        form_scan.addRow("Z 结束位置 (mm):", self.edtZEnd)
        form_scan.addRow("Z 步长 (mm):",     self.edtZStep)
        form_scan.addRow("每步延时 (s):",    self.edtDelay)
        grp_scan.setLayout(form_scan)
        layout.addWidget(grp_scan)

        # ── 点云过滤参数 ──────────────────────────────────────
        grp_pc = QGroupBox("点云参数")
        form_pc = QFormLayout()
        form_pc.setLabelAlignment(Qt.AlignRight)
        self.edtZScale       = QLineEdit("1.0")
        self.edtMinSharpness = QLineEdit("20.0")
        self.edtZScale      .setToolTip("Z 轴方向缩放系数（1.0 = 不缩放）")
        self.edtMinSharpness.setToolTip("最小锐度阈值，低于此值的像素将被过滤掉（去除背景噪点）")
        form_pc.addRow("Z 轴缩放系数:",   self.edtZScale)
        form_pc.addRow("最小锐度阈值:",  self.edtMinSharpness)
        grp_pc.setLayout(form_pc)
        layout.addWidget(grp_pc)

        # ── 进度条与状态 ──────────────────────────────────────
        self.progressBar = QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.setTextVisible(True)
        layout.addWidget(self.progressBar)

        self.lblStatus = QLabel("就绪 — 请确认相机已开启采集且串口已连接")
        self.lblStatus.setWordWrap(True)
        self.lblStatus.setStyleSheet("color: gray; padding: 2px;")
        layout.addWidget(self.lblStatus)

        # ── 操作按钮 ──────────────────────────────────────────
        btn_row1 = QHBoxLayout()
        self.bnStart = QPushButton("▶  开始重建")
        self.bnStop  = QPushButton("■  停止")
        self.bnStart.setMinimumHeight(32)
        self.bnStop .setMinimumHeight(32)
        self.bnStop .setEnabled(False)
        btn_row1.addWidget(self.bnStart)
        btn_row1.addWidget(self.bnStop)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.bnVisualize = QPushButton("📊  可视化点云")
        self.bnExport    = QPushButton("💾  导出点云")
        self.bnVisualize.setMinimumHeight(30)
        self.bnExport   .setMinimumHeight(30)
        self.bnVisualize.setEnabled(False)
        self.bnExport   .setEnabled(False)
        btn_row2.addWidget(self.bnVisualize)
        btn_row2.addWidget(self.bnExport)
        layout.addLayout(btn_row2)

        # ── 信号连接 ──────────────────────────────────────────
        self.bnStart    .clicked.connect(self._start_reconstruction)
        self.bnStop     .clicked.connect(self._stop_reconstruction)
        self.bnVisualize.clicked.connect(self._visualize_point_cloud)
        self.bnExport   .clicked.connect(self._export_point_cloud)

    # ── 辅助 ─────────────────────────────────────────────────

    def _set_status(self, msg, color="gray"):
        self.lblStatus.setText(msg)
        self.lblStatus.setStyleSheet(
            "color: {}; padding: 2px;".format(color))

    def _send_serial(self, cmd):
        """线程安全串口发送（不弹窗，仅打印）"""
        try:
            if not is_serial_connected or serial_conn is None:
                print("[Recon3D] 串口未连接，无法发送: {}".format(cmd.strip()))
                return False
            serial_conn.write(cmd.encode('utf-8'))
            print("[Recon3D] >>", cmd.strip())
            return True
        except Exception as e:
            print("[Recon3D] 串口发送异常:", e)
            return False

    # ── 重建控制 ──────────────────────────────────────────────

    def _start_reconstruction(self):
        """校验参数后启动重建后台线程"""
        try:
            z_start = float(self.edtZStart.text().strip())
            z_end   = float(self.edtZEnd.text().strip())
            z_step  = float(self.edtZStep.text().strip())
            delay   = float(self.edtDelay.text().strip())
            if z_step <= 0:
                raise ValueError("步长必须为正数")
            if z_start >= z_end:
                raise ValueError("起始位置必须小于结束位置")
            if delay < 0:
                raise ValueError("延时不能为负数")
            n_steps = int(round((z_end - z_start) / z_step)) + 1
            if n_steps < 2:
                raise ValueError("步数过少（{}步），请减小步长或增大扫描范围".format(n_steps))
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return

        if not isGrabbing:
            QMessageBox.warning(self, "错误", "请先开启相机采集！")
            return
        if not is_serial_connected:
            QMessageBox.warning(self, "错误", "请先连接串口（用于控制 Z 轴运动）！")
            return

        reply = QMessageBox.question(
            self, "确认",
            "将扫描 Z 轴 {:.2f} → {:.2f} mm，步长 {:.3f} mm，共 {} 步。\n"
            "确认开始？".format(z_start, z_end, z_step, n_steps),
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._running = True
        self._depth_map   = None
        self._point_cloud = None
        self.bnStart    .setEnabled(False)
        self.bnStop     .setEnabled(True)
        self.bnVisualize.setEnabled(False)
        self.bnExport   .setEnabled(False)
        self.progressBar.setValue(0)
        self._set_status("准备中…", "blue")

        self._worker_thread = threading.Thread(
            target=self._recon_worker,
            args=(z_start, z_end, z_step, delay),
            daemon=True)
        self._worker_thread.start()

    def _stop_reconstruction(self):
        self._running = False
        self._set_status("停止请求已发送，等待当前步完成…", "orange")

    # ── 核心重建后台线程 ──────────────────────────────────────

    def _recon_worker(self, z_start, z_end, z_step, delay):
        """
        深度从焦点（Depth From Focus）三维重建后台线程

        步骤：
          1. 移动到 Z 起始位置
          2. 逐步扫描 Z 轴采集锐度栈
          3. 每像素取最大锐度对应 Z 值生成深度图
          4. 利用 pixels_per_mm 将像素坐标转换为物理坐标（mm）
          5. 过滤低锐度点后生成并存储点云
        """
        try:
            import numpy as np
        except ImportError:
            QTimer.singleShot(0, lambda: QMessageBox.critical(
                self, "依赖缺失", "三维重建需要 numpy:\npip install numpy"))
            self._running = False
            QTimer.singleShot(0, self._on_worker_done)
            return

        def set_status(msg, color="blue"):
            QTimer.singleShot(0, lambda m=msg, c=color: self._set_status(m, c))

        def set_progress(v):
            QTimer.singleShot(0, lambda val=v: self.progressBar.setValue(val))

        try:
            n_steps = int(round((z_end - z_start) / z_step)) + 1
            z_positions = [z_start + i * z_step for i in range(n_steps)]

            # ── 移动到起始 Z 位置 ─────────────────────────────
            set_status("移动到起始位置 Z={:.3f} mm…".format(z_start))
            print("[Recon3D] ===== 三维重建开始 =====")
            print("[Recon3D] 扫描范围: {:.3f} ~ {:.3f} mm, 步长 {:.3f} mm, {} 步".format(
                z_start, z_end, z_step, n_steps))

            if not self._send_serial("G90\n"):
                set_status("错误：无法发送归位指令（G90）", "red"); return
            if not self._send_serial("G1 Z{:.4f} F300\n".format(z_start)):
                set_status("错误：无法移动到起始位置", "red"); return
            # 等待运动完成
            wait = max(0.8, abs(z_start) / 5.0 + 0.4)
            time.sleep(wait)

            # ── 获取图像尺寸 ───────────────────────────────────
            set_status("探测图像尺寸…")
            data0, w, h = obj_cam_operation.Get_frame_numpy()
            if data0 is None or w == 0 or h == 0:
                set_status("错误：无法获取相机帧，请检查相机是否正在输出图像", "red")
                return
            print("[Recon3D] 图像尺寸: {}×{}".format(w, h))

            # ── 分配锐度栈与强度栈 ─────────────────────────────
            sharpness_stack = np.zeros((n_steps, h, w), dtype=np.float32)
            intensity_stack  = np.zeros((n_steps, h, w), dtype=np.float32)

            # ── 逐步扫描 ───────────────────────────────────────
            for idx, z_pos in enumerate(z_positions):
                if not self._running:
                    set_status("已停止", "orange")
                    return

                # 从第二步开始相对步进
                if idx > 0:
                    if not self._send_serial("G91\n"):
                        set_status("错误：G91 发送失败", "red"); return
                    if not self._send_serial("G1 Z{:.4f} F300\n".format(z_step)):
                        set_status("错误：步进移动失败", "red"); return
                    if not self._send_serial("G90\n"):
                        set_status("错误：G90 发送失败", "red"); return
                    time.sleep(delay)

                set_status("扫描 Z={:.3f} mm  ({}/{})".format(z_pos, idx + 1, n_steps))

                # 采集帧
                data, fw, fh = obj_cam_operation.Get_frame_numpy()
                if data is not None and fw == w and fh == h and len(data) >= w * h:
                    gray = data[:w * h].reshape(h, w).astype(np.float32)

                    # 拉普拉斯锐度图（平方保证非负）
                    lap = (gray[:-2, 1:-1] + gray[2:, 1:-1] +
                           gray[1:-1, :-2] + gray[1:-1, 2:] -
                           4.0 * gray[1:-1, 1:-1])
                    sharp_map = np.zeros((h, w), dtype=np.float32)
                    sharp_map[1:-1, 1:-1] = lap * lap   # L²
                    sharpness_stack[idx] = sharp_map
                    intensity_stack[idx] = gray
                else:
                    print("[Recon3D] [警告] 第 {} 步帧获取失败，跳过".format(idx + 1))

                set_progress(int((idx + 1) / n_steps * 80))

            if not self._running:
                set_status("已停止", "orange")
                return

            # ── 生成深度图 ─────────────────────────────────────
            set_status("生成深度图…")
            set_progress(82)

            # 每像素最大锐度对应的 Z 层索引
            best_z_idx  = np.argmax(sharpness_stack, axis=0)   # (h, w)
            best_sharp  = np.max(sharpness_stack, axis=0)       # (h, w)
            z_arr       = np.array(z_positions, dtype=np.float32)
            depth_map   = z_arr[best_z_idx]                     # (h, w), mm

            # 取该位置对应层的灰度作为点强度
            row_idx, col_idx = np.indices((h, w))
            best_intensity = intensity_stack[best_z_idx, row_idx, col_idx]

            set_progress(88)

            # ── 生成点云 ───────────────────────────────────────
            set_status("生成点云…")

            try:
                min_sharp = float(self.edtMinSharpness.text().strip())
                if min_sharp < 0:
                    min_sharp = 0.0
            except ValueError:
                min_sharp = 20.0
            try:
                z_scale = float(self.edtZScale.text().strip())
            except ValueError:
                z_scale = 1.0

            valid_mask = best_sharp > min_sharp

            # 像素坐标 → 物理坐标（mm），以图像中心为原点
            ppmm = pixels_per_mm if pixels_per_mm > 0 else 1.0
            ys, xs = np.where(valid_mask)
            x_mm  = (xs.astype(np.float32) - w / 2.0) / ppmm
            y_mm  = (ys.astype(np.float32) - h / 2.0) / ppmm
            z_mm  = depth_map[ys, xs] * z_scale
            intensity_vals = best_intensity[ys, xs]

            point_cloud = np.column_stack(
                [x_mm, y_mm, z_mm, intensity_vals]).astype(np.float32)

            self._depth_map   = depth_map
            self._point_cloud = point_cloud
            self._img_size    = (w, h)

            set_progress(100)
            n_pts = len(point_cloud)
            coverage = 100.0 * n_pts / (w * h) if (w * h) > 0 else 0.0
            msg = ("重建完成 ✓   点数: {:,}   像素覆盖率: {:.1f}%\n"
                   "pixels/mm={:.2f}  分辨率: {}×{}".format(
                       n_pts, coverage, ppmm, w, h))
            set_status(msg, "green")
            print("[Recon3D] 完成: {:,} 点, {}×{} 像素, 覆盖率 {:.1f}%".format(
                n_pts, w, h, coverage))

            QTimer.singleShot(0, lambda: self.bnVisualize.setEnabled(True))
            QTimer.singleShot(0, lambda: self.bnExport.setEnabled(True))

        except Exception as e:
            import traceback
            traceback.print_exc()
            QTimer.singleShot(0, lambda err=str(e): self._set_status(
                "重建失败: " + err, "red"))
        finally:
            self._running = False
            QTimer.singleShot(0, self._on_worker_done)

    def _on_worker_done(self):
        self.bnStart.setEnabled(True)
        self.bnStop .setEnabled(False)

    # ── 可视化 ────────────────────────────────────────────────

    def _visualize_point_cloud(self):
        """使用 matplotlib 在新窗口中显示深度图和三维点云散点图"""
        if self._point_cloud is None or len(self._point_cloud) == 0:
            QMessageBox.warning(self, "提示", "暂无点云数据，请先执行重建。")
            return
        try:
            import numpy as np
            import matplotlib
            matplotlib.use('Qt5Agg')
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

            pc = self._point_cloud
            x, y, z, intensity = pc[:, 0], pc[:, 1], pc[:, 2], pc[:, 3]
            fp = _get_mpl_font()

            fig = plt.figure(figsize=(14, 6))
            title_kw = {'fontproperties': fp} if fp else {}
            fig.suptitle("三维重建结果 — 点云数据", fontsize=14, **title_kw)

            # 左图：深度图（热力图）
            ax1 = fig.add_subplot(1, 2, 1)
            if self._depth_map is not None:
                w, h = self._img_size
                im = ax1.imshow(self._depth_map, cmap='plasma',
                                origin='upper',
                                extent=[-w / (2 * pixels_per_mm),
                                        w / (2 * pixels_per_mm),
                                        h / (2 * pixels_per_mm),
                                        -h / (2 * pixels_per_mm)])
                cb = plt.colorbar(im, ax=ax1)
                cb.set_label('Depth (mm)')
                ax1.set_title("Depth Map", **title_kw)
                ax1.set_xlabel("X (mm)")
                ax1.set_ylabel("Y (mm)")

            # 右图：三维点云
            ax2 = fig.add_subplot(1, 2, 2, projection='3d')
            # 降采样以提高渲染速度（最多显示 60000 点）
            MAX_PLOT = 60000
            if len(x) > MAX_PLOT:
                idx = np.random.choice(len(x), MAX_PLOT, replace=False)
                xp, yp, zp, ip = x[idx], y[idx], z[idx], intensity[idx]
            else:
                xp, yp, zp, ip = x, y, z, intensity

            sc = ax2.scatter(xp, yp, zp, c=ip, cmap='gray', s=0.5, alpha=0.6)
            plt.colorbar(sc, ax=ax2, label='Intensity')
            ax2.set_xlabel("X (mm)")
            ax2.set_ylabel("Y (mm)")
            ax2.set_zlabel("Z (mm)")
            ax2.set_title("Point Cloud ({:,} pts)".format(len(x)), **title_kw)

            plt.tight_layout()
            plt.show()

        except ImportError:
            QMessageBox.warning(self, "依赖缺失",
                                "可视化需要 matplotlib:\n"
                                "pip install matplotlib")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "可视化错误", str(e))

    # ── 导出 ──────────────────────────────────────────────────

    def _export_point_cloud(self):
        """将点云导出为 .ply（ASCII）或 .csv 文件"""
        if self._point_cloud is None or len(self._point_cloud) == 0:
            QMessageBox.warning(self, "提示", "暂无点云数据，请先执行重建。")
            return

        default_name = "pointcloud_{}.ply".format(
            datetime.now().strftime("%Y%m%d_%H%M%S"))
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出点云",
            os.path.join(get_effective_save_path(), default_name),
            "PLY 文件 (*.ply);;CSV 文件 (*.csv);;全部文件 (*.*)")
        if not file_path:
            return

        try:
            pc = self._point_cloud
            n_pts = len(pc)

            if file_path.lower().endswith('.csv'):
                import csv
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['x_mm', 'y_mm', 'z_mm', 'intensity'])
                    writer.writerows(pc.tolist())
                QMessageBox.information(
                    self, "导出完成",
                    "已导出 {:,} 个点（CSV 格式）\n{}".format(n_pts, file_path))
            else:
                # PLY ASCII 格式（兼容 MeshLab / CloudCompare / Open3D）
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("ply\n")
                    f.write("format ascii 1.0\n")
                    f.write("comment Generated by BasicDemo 3D Reconstruction\n")
                    f.write("comment pixels_per_mm={:.4f}\n".format(pixels_per_mm))
                    f.write("element vertex {}\n".format(n_pts))
                    f.write("property float x\n")
                    f.write("property float y\n")
                    f.write("property float z\n")
                    f.write("property float intensity\n")
                    f.write("end_header\n")
                    for row in pc:
                        f.write("{:.6f} {:.6f} {:.6f} {:.2f}\n".format(
                            float(row[0]), float(row[1]),
                            float(row[2]), float(row[3])))
                QMessageBox.information(
                    self, "导出完成",
                    "已导出 {:,} 个点（PLY 格式）\n"
                    "支持 MeshLab / CloudCompare / Open3D 打开\n{}".format(
                        n_pts, file_path))
            print("[Recon3D] 点云已导出: {}".format(file_path))
        except Exception as e:
            QMessageBox.warning(self, "导出错误", str(e))


# ──────────────────────────────────────────────────────────────────
#  以时间换位深度（嵌套叠叠乐）— 连续扫描 + 时间映射 Z 位置
# ──────────────────────────────────────────────────────────────────

class TemporalDepthDialog(QDialog):
    """
    以时间换位深度 对话框（嵌套叠叠乐算法）

    核心思路：
      与传统"停-拍-移"DFF 不同，本方法让 Z 轴做 **匀速连续运动**，
      相机同时以固定间隔持续采帧，每帧的 Z 位置由
          z(t) = z_start + speed × elapsed_time
      推算，不需要串口应答轮询。
      采集结束后可选择 **嵌套精扫**（Nested Pass）：
        自动在粗扫的最佳焦深区间内以更低速度/更密采样再做一次，
        将两轮数据叠加融合，层层叠加，逐步提升深度精度——
        这正是"叠叠乐"（嵌套 Jenga 积木）的命名由来。

    算法流程：
      1. 发送 G1 Z{end} F{speed*60} 让 Z 轴开始匀速运动
      2. 每隔 interval_ms 采一帧，记录 [timestamp, 帧数据]
      3. 运动估计完成（时间到）后停止 Z 轴
      4. 利用时间戳把每帧映射到 Z 位置，构建锐度栈
      5. 逐像素取最大锐度对应 Z → 深度图 → 点云
      6. 可选：检测粗扫中平均锐度最高的 Z 子区间，自动执行第二轮细扫
         并将细扫锐度栈叠加融合到粗扫结果中（嵌套叠叠乐核心）
    """

    # ── 信号桥（在后台线程里安全更新 UI）────────────────────────
    _sig_status   = pyqtSignal(str, str)    # message, color
    _sig_progress = pyqtSignal(int)
    _sig_log      = pyqtSignal(str)
    _sig_done     = pyqtSignal(bool, str)   # success, summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("以时间换位深度 — 嵌套叠叠乐")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        self._running   = False
        self._worker    = None
        self._depth_map = None
        self._pc        = None          # 点云 (N,4): x_mm, y_mm, z_mm, intensity
        self._img_size  = (0, 0)
        self._pass_merged_sharp  = None # 融合后最大锐度图（用于阈值过滤）
        self._setup_ui()
        # 连接信号
        self._sig_status  .connect(self._on_status)
        self._sig_progress.connect(self.progressBar.setValue)
        self._sig_log     .connect(self._append_log)
        self._sig_done    .connect(self._on_done)

    # ── UI 构建────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ── 粗扫参数 ─────────────────────────────────────────────
        grp1 = QGroupBox("第一轮：粗扫参数（连续匀速扫描）")
        f1 = QFormLayout()
        f1.setLabelAlignment(Qt.AlignRight)
        self.edtZ0     = QLineEdit("-2.0")
        self.edtZ1     = QLineEdit("2.0")
        self.edtSpeed  = QLineEdit("1.0")
        self.edtItvMs  = QLineEdit("80")
        self.edtZ0   .setToolTip("Z 轴绝对坐标起始位置（mm）")
        self.edtZ1   .setToolTip("Z 轴绝对坐标结束位置（mm）")
        self.edtSpeed.setToolTip("Z 轴运动速度（mm/s），越慢采样越密")
        self.edtItvMs.setToolTip("相机采帧间隔（毫秒），建议 50-200ms")
        f1.addRow("Z 起始 (mm):",   self.edtZ0)
        f1.addRow("Z 结束 (mm):",   self.edtZ1)
        f1.addRow("扫描速度 (mm/s):", self.edtSpeed)
        f1.addRow("采帧间隔 (ms):",  self.edtItvMs)
        grp1.setLayout(f1)
        root.addWidget(grp1)

        # ── 嵌套精扫参数 ──────────────────────────────────────────
        grp2 = QGroupBox("第二轮：嵌套精扫（叠叠乐）")
        f2 = QFormLayout()
        f2.setLabelAlignment(Qt.AlignRight)
        self.chkNested    = QCheckBox("启用嵌套精扫（粗扫结束后自动执行）")
        self.chkNested.setChecked(True)
        self.edtFineSpeed = QLineEdit("0.3")
        self.edtFineItvMs = QLineEdit("50")
        self.edtFinePct   = QLineEdit("30")
        self.edtFineSpeed.setToolTip("精扫速度（mm/s），建议 ≤ 1/3 粗扫速度")
        self.edtFineItvMs.setToolTip("精扫采帧间隔（ms），建议比粗扫更密")
        self.edtFinePct  .setToolTip("在粗扫结果中截取平均锐度最高的 N% 区间作为精扫范围")
        f2.addRow(self.chkNested)
        f2.addRow("精扫速度 (mm/s):",   self.edtFineSpeed)
        f2.addRow("精扫采帧间隔 (ms):", self.edtFineItvMs)
        f2.addRow("聚焦区间比例 (%):",  self.edtFinePct)
        grp2.setLayout(f2)
        root.addWidget(grp2)

        # ── 点云参数 ──────────────────────────────────────────────
        grp3 = QGroupBox("点云参数")
        f3 = QFormLayout()
        f3.setLabelAlignment(Qt.AlignRight)
        self.edtMinSharp = QLineEdit("10.0")
        self.edtZScale   = QLineEdit("1.0")
        self.edtMinSharp.setToolTip("最大锐度低于此值的像素将被过滤（去除背景/模糊区）")
        self.edtZScale  .setToolTip("Z 轴方向缩放系数（1.0 = 不缩放）")
        f3.addRow("最小锐度阈值:", self.edtMinSharp)
        f3.addRow("Z 轴缩放系数:", self.edtZScale)
        grp3.setLayout(f3)
        root.addWidget(grp3)

        # ── 进度 & 状态 ──────────────────────────────────────────
        self.progressBar = QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setTextVisible(True)
        root.addWidget(self.progressBar)

        self.lblStatus = QLabel("就绪 — 请确认相机已开启采集（串口连接可选）")
        self.lblStatus.setWordWrap(True)
        self.lblStatus.setStyleSheet("color: gray; padding: 2px;")
        root.addWidget(self.lblStatus)

        # ── 运行日志 ──────────────────────────────────────────────
        self.txtLog = QPlainTextEdit()
        self.txtLog.setReadOnly(True)
        self.txtLog.setMaximumHeight(120)
        self.txtLog.setPlaceholderText("运行日志…")
        root.addWidget(self.txtLog)

        # ── 按钮行 ────────────────────────────────────────────────
        row1 = QHBoxLayout()
        self.bnStart = QPushButton("▶  开始扫描")
        self.bnStop  = QPushButton("■  停止")
        self.bnStart.setMinimumHeight(32)
        self.bnStop .setMinimumHeight(32)
        self.bnStop .setEnabled(False)
        row1.addWidget(self.bnStart)
        row1.addWidget(self.bnStop)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.bnViz    = QPushButton("📊  可视化点云")
        self.bnExport = QPushButton("💾  导出点云")
        self.bnViz   .setMinimumHeight(30)
        self.bnExport.setMinimumHeight(30)
        self.bnViz   .setEnabled(False)
        self.bnExport.setEnabled(False)
        row2.addWidget(self.bnViz)
        row2.addWidget(self.bnExport)
        root.addLayout(row2)

        # ── 信号 ──────────────────────────────────────────────────
        self.bnStart .clicked.connect(self._start)
        self.bnStop  .clicked.connect(self._stop)
        self.bnViz   .clicked.connect(self._visualize)
        self.bnExport.clicked.connect(self._export)

    # ── 槽函数 ────────────────────────────────────────────────────

    def _on_status(self, msg, color):
        self.lblStatus.setText(msg)
        self.lblStatus.setStyleSheet("color: {}; padding: 2px;".format(color))

    def _append_log(self, msg):
        self.txtLog.appendPlainText(msg)
        sb = self.txtLog.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, success, summary):
        self.bnStart .setEnabled(True)
        self.bnStop  .setEnabled(False)
        if success:
            self.bnViz   .setEnabled(True)
            self.bnExport.setEnabled(True)

    # ── 参数解析 helper ──────────────────────────────────────────

    def _parse_params(self):
        """解析并校验所有参数，返回 dict 或抛出 ValueError"""
        z0    = float(self.edtZ0.text().strip())
        z1    = float(self.edtZ1.text().strip())
        speed = float(self.edtSpeed.text().strip())
        itv   = float(self.edtItvMs.text().strip()) / 1000.0
        nested     = self.chkNested.isChecked()
        fine_speed = float(self.edtFineSpeed.text().strip())
        fine_itv   = float(self.edtFineItvMs.text().strip()) / 1000.0
        fine_pct   = float(self.edtFinePct.text().strip())
        min_sharp  = float(self.edtMinSharp.text().strip())
        z_scale    = float(self.edtZScale.text().strip())

        if z0 >= z1:        raise ValueError("Z 起始必须小于 Z 结束")
        if speed <= 0:      raise ValueError("速度必须为正数")
        if itv <= 0:        raise ValueError("采帧间隔必须为正数")
        if fine_speed <= 0: raise ValueError("精扫速度必须为正数")
        if fine_itv <= 0:   raise ValueError("精扫采帧间隔必须为正数")
        if not (1 <= fine_pct <= 100):
            raise ValueError("聚焦区间比例须在 1~100 之间")

        sweep_s = (z1 - z0) / speed
        n_est   = int(sweep_s / itv) + 1
        if n_est < 3:
            raise ValueError("预估采帧数过少（{}帧），请降低速度或缩小采帧间隔".format(n_est))
        return dict(z0=z0, z1=z1, speed=speed, itv=itv,
                    nested=nested, fine_speed=fine_speed, fine_itv=fine_itv,
                    fine_pct=fine_pct, min_sharp=min_sharp, z_scale=z_scale,
                    sweep_s=sweep_s, n_est=n_est)

    # ── 启动/ 停止 ────────────────────────────────────────────────

    def _start(self):
        try:
            p = self._parse_params()
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        if not isGrabbing:
            QMessageBox.warning(self, "错误", "请先开启相机采集！")
            return

        nest_note = ("  + 嵌套精扫：速度 {:.2f} mm/s，采帧间隔 {:.0f} ms，"
                     "聚焦区间前 {:.0f}%\n".format(
                         p['fine_speed'], p['fine_itv'] * 1000, p['fine_pct'])
                     if p['nested'] else "  （不执行嵌套精扫）\n")
        msg = ("Z 轴将匀速从 {:.2f} mm 扫描到 {:.2f} mm\n"
               "速度 {:.2f} mm/s，预计用时 {:.1f}s，约 {} 帧\n"
               "采帧间隔 {:.0f} ms\n"
               "{}确认开始？".format(
                   p['z0'], p['z1'], p['speed'], p['sweep_s'], p['n_est'],
                   p['itv'] * 1000, nest_note))
        if QMessageBox.question(self, "确认", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        self._running   = True
        self._depth_map = None
        self._pc        = None
        self.bnStart .setEnabled(False)
        self.bnStop  .setEnabled(True)
        self.bnViz   .setEnabled(False)
        self.bnExport.setEnabled(False)
        self.progressBar.setValue(0)
        self.txtLog.clear()
        self._sig_status.emit("准备中…", "blue")

        self._worker = threading.Thread(
            target=self._worker_fn, args=(p,), daemon=True)
        self._worker.start()

    def _stop(self):
        self._running = False
        self._sig_status.emit("停止请求已发送…", "orange")

    # ── 串口发送（不弹窗）────────────────────────────────────────

    def _gcode(self, cmd):
        try:
            if is_serial_connected and serial_conn is not None:
                serial_conn.write(cmd.encode('utf-8'))
                self._sig_log.emit("  >> " + cmd.strip())
                return True
            self._sig_log.emit("  [串口未连接，跳过: {}]".format(cmd.strip()))
            return False
        except Exception as e:
            self._sig_log.emit("  [串口错误: {}]".format(e))
            return False

    # ── 单次连续扫描采集 ─────────────────────────────────────────

    def _do_sweep(self, z0, z1, speed, itv, label="粗扫"):
        """
        执行一次连续 Z 轴扫描，返回 (frames_gray_list, z_list) 或 (None, None)。
        frames_gray_list: list of np.ndarray (h, w) float32
        z_list:           list of float  — 每帧对应的估算 Z 位置 (mm)
        """
        import numpy as np
        sweep_s = abs(z1 - z0) / speed

        # 先移动到起始位置
        self._sig_status.emit("{} — 移动到起始 Z={:.3f}mm…".format(label, z0), "blue")
        self._gcode("G90\n")
        self._gcode("G1 Z{:.4f} F300\n".format(z0))
        wait = max(0.8, abs(z0) / 5.0 + 0.5)
        t_pre = time.time()
        while time.time() - t_pre < wait:
            if not self._running:
                return None, None
            time.sleep(0.05)

        # 探测图像尺寸
        data0, w, h = obj_cam_operation.Get_frame_numpy()
        if data0 is None or w == 0 or h == 0:
            self._sig_status.emit("错误：无法获取相机帧", "red")
            return None, None
        self._sig_log.emit("  图像尺寸 {}×{}".format(w, h))

        # 发出匀速运动指令（F 单位 mm/min）
        feedrate = speed * 60.0
        self._sig_status.emit("{} — Z 轴开始匀速扫描，速度 {:.2f} mm/s…".format(label, speed), "blue")
        self._gcode("G1 Z{:.4f} F{:.1f}\n".format(z1, feedrate))
        t_start = time.time()

        frames_gray = []
        z_list      = []
        next_cap    = t_start

        while self._running:
            now = time.time()
            elapsed = now - t_start

            # 时间映射 Z 位置
            z_est = z0 + (z1 - z0) * min(elapsed / sweep_s, 1.0)

            # 采帧
            if now >= next_cap:
                data, fw, fh = obj_cam_operation.Get_frame_numpy()
                if data is not None and fw == w and fh == h and len(data) >= w * h:
                    gray = data[:w * h].reshape(h, w).astype(np.float32)
                    frames_gray.append(gray)
                    z_list.append(z_est)
                next_cap += itv

            # 更新进度（此方法返回 0-50 段由调用方按需缩放）
            frac = min(elapsed / sweep_s, 1.0)
            if label == "粗扫":
                self._sig_progress.emit(int(frac * 45))
            else:
                self._sig_progress.emit(50 + int(frac * 30))

            # 运动估算完成退出
            if elapsed >= sweep_s + 0.3:   # 多等 300ms 让 Z 稳定
                break
            time.sleep(max(0, next_cap - time.time()))

        # 停止 Z 轴（发送当前估算位置）
        self._gcode("G1 Z{:.4f} F300\n".format(z_est if z_list else z1))
        self._sig_log.emit("  {} 结束：采集 {} 帧，Z 估算范围 {:.3f}~{:.3f} mm".format(
            label, len(frames_gray),
            min(z_list) if z_list else z0,
            max(z_list) if z_list else z1))
        return frames_gray, z_list

    # ── 构建锐度栈 → 深度图 helper ─────────────────────────────

    @staticmethod
    def _build_sharpness_stack(frames_gray, z_list):
        """
        将帧列表构建为稀疏锐度栈。
        返回 depth_map (h, w), max_sharp (h, w)。
        使用增量式更新（内存友好），不保留完整 N×H×W 栈。
        """
        import numpy as np
        if not frames_gray:
            return None, None
        h, w = frames_gray[0].shape
        best_sharp = np.zeros((h, w), dtype=np.float32)  # 每像素最大锐度
        best_z_map = np.zeros((h, w), dtype=np.float32)  # 对应 Z 值
        best_gray  = np.zeros((h, w), dtype=np.float32)  # 对应灰度（强度）

        for gray, z_pos in zip(frames_gray, z_list):
            # 拉普拉斯平方锐度图
            lap = (gray[:-2, 1:-1] + gray[2:, 1:-1] +
                   gray[1:-1, :-2] + gray[1:-1, 2:] -
                   4.0 * gray[1:-1, 1:-1])
            sharp = np.zeros((h, w), dtype=np.float32)
            sharp[1:-1, 1:-1] = lap * lap
            # 增量最大值更新
            mask = sharp > best_sharp
            best_sharp[mask] = sharp[mask]
            best_z_map[mask] = z_pos
            best_gray [mask] = gray[mask]

        return best_z_map, best_sharp, best_gray

    # ── 核心后台工作线程 ─────────────────────────────────────────

    def _worker_fn(self, p):
        try:
            import numpy as np
        except ImportError:
            self._sig_status.emit("三维重建需要 numpy，请执行 pip install numpy", "red")
            self._running = False
            self._sig_done.emit(False, "")
            return

        try:
            self._sig_log.emit("═══ 开始 以时间换位深度（嵌套叠叠乐） ═══")
            self._sig_log.emit("粗扫: Z {:.2f}→{:.2f}mm  速度 {:.2f}mm/s  采帧 {:.0f}ms".format(
                p['z0'], p['z1'], p['speed'], p['itv'] * 1000))

            # ══ 第一轮：粗扫 ══════════════════════════════════════
            self._sig_status.emit("第一轮 粗扫…", "blue")
            frames1, zlist1 = self._do_sweep(
                p['z0'], p['z1'], p['speed'], p['itv'], label="粗扫")
            if not self._running or frames1 is None or len(frames1) < 3:
                self._sig_status.emit(
                    "粗扫{}".format("已停止" if not self._running else "帧不足，请检查相机"), "orange")
                self._sig_done.emit(False, "")
                return

            self._sig_log.emit("粗扫完成，共 {} 帧".format(len(frames1)))
            self._sig_progress.emit(48)

            # 建立粗扫锐度栈
            depth_map, sharp_map, gray_map = self._build_sharpness_stack(frames1, zlist1)
            if depth_map is None:
                self._sig_status.emit("锐度栈生成失败", "red")
                self._sig_done.emit(False, "")
                return
            h, w = depth_map.shape
            self._img_size = (w, h)
            self._sig_progress.emit(52)

            # ══ 第二轮：嵌套精扫（叠叠乐）══════════════════════════
            if p['nested'] and self._running:
                self._sig_log.emit("── 嵌套精扫开始 ──────────────────────────────")
                # 定位粗扫中平均锐度最高的 Z 子区间
                # 将 Z 范围分成若干 bin，找到 top-N% 的 Z 区间
                n_bins    = max(10, len(frames1))
                z_min_val = float(min(zlist1))
                z_max_val = float(max(zlist1))
                bin_edges = np.linspace(z_min_val, z_max_val, n_bins + 1)
                bin_sharp = np.zeros(n_bins, dtype=np.float64)
                bin_count = np.zeros(n_bins, dtype=np.int32)

                for i, (frame, z_pos) in enumerate(zip(frames1, zlist1)):
                    b = min(int((z_pos - z_min_val) / (z_max_val - z_min_val + 1e-9) * n_bins),
                            n_bins - 1)
                    lap = (frame[:-2, 1:-1] + frame[2:, 1:-1] +
                           frame[1:-1, :-2] + frame[1:-1, 2:] -
                           4.0 * frame[1:-1, 1:-1])
                    bin_sharp[b] += float(np.mean(lap * lap))
                    bin_count[b] += 1

                # 取覆盖 fine_pct% 行程的最高锐度 bin 区间
                mean_sharp = np.where(bin_count > 0,
                                      bin_sharp / np.maximum(bin_count, 1), 0.0)
                n_select = max(1, int(n_bins * p['fine_pct'] / 100.0))
                top_bins = np.argsort(mean_sharp)[::-1][:n_select]
                fz0 = float(bin_edges[min(top_bins)])
                fz1 = float(bin_edges[min(max(top_bins) + 1, n_bins)])
                # 保证精扫范围至少 0.1mm
                if fz1 - fz0 < 0.1:
                    mid = (fz0 + fz1) / 2.0
                    fz0, fz1 = mid - 0.05, mid + 0.05

                self._sig_log.emit("  精扫区间: {:.3f} ~ {:.3f} mm  (Delta {:.3f} mm)".format(
                    fz0, fz1, fz1 - fz0))

                frames2, zlist2 = self._do_sweep(
                    fz0, fz1, p['fine_speed'], p['fine_itv'], label="精扫")

                if frames2 and len(frames2) >= 2 and self._running:
                    self._sig_log.emit("  精扫帧数: {}".format(len(frames2)))
                    # 用精扫数据更新融合锐度栈（叠加）
                    depth_f, sharp_f, gray_f = self._build_sharpness_stack(frames2, zlist2)
                    if depth_f is not None:
                        mask = sharp_f > sharp_map
                        sharp_map[mask] = sharp_f[mask]
                        depth_map[mask] = depth_f[mask]
                        gray_map [mask] = gray_f [mask]
                        n_upd = int(np.sum(mask))
                        self._sig_log.emit("  叠叠乐融合: {:,} 个像素由精扫更新".format(n_upd))
                else:
                    self._sig_log.emit("  精扫帧不足或已停止，跳过融合")
            elif not p['nested']:
                self._sig_log.emit("（未启用嵌套精扫）")

            if not self._running:
                self._sig_status.emit("已停止", "orange")
                self._sig_done.emit(False, "")
                return

            self._sig_progress.emit(85)
            self._sig_status.emit("生成点云…", "blue")

            # ══ 生成点云 ══════════════════════════════════════════
            z_scale   = p['z_scale']
            min_sharp = p['min_sharp']
            ppmm      = pixels_per_mm if pixels_per_mm > 0 else 1.0

            valid = sharp_map > min_sharp
            ys, xs = np.where(valid)
            if len(xs) == 0:
                self._sig_status.emit(
                    "没有找到有效点！请降低最小锐度阈值（当前 {:.1f}）".format(min_sharp), "red")
                self._sig_done.emit(False, "")
                return

            x_mm = (xs.astype(np.float32) - w / 2.0) / ppmm
            y_mm = (ys.astype(np.float32) - h / 2.0) / ppmm
            z_mm = depth_map[ys, xs] * z_scale
            intv = gray_map [ys, xs]

            self._pc        = np.column_stack([x_mm, y_mm, z_mm, intv]).astype(np.float32)
            self._depth_map = depth_map
            self._sharp_map = sharp_map

            self._sig_progress.emit(100)
            n_pts   = len(self._pc)
            cov_pct = 100.0 * n_pts / (w * h)
            summary = ("扫描完成 ✓   点数: {:,}   覆盖率: {:.1f}%\n"
                       "pixels/mm={:.2f}  图像 {}×{}".format(
                           n_pts, cov_pct, ppmm, w, h))
            self._sig_status.emit(summary, "green")
            self._sig_log.emit("═══ 完成：{:,} 点，覆盖率 {:.1f}% ═══".format(n_pts, cov_pct))
            self._sig_done.emit(True, summary)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._sig_status.emit("发生异常: " + str(e), "red")
            self._sig_log.emit("[ERROR] " + str(e))
            self._sig_done.emit(False, "")
        finally:
            self._running = False

    # ── 可视化 ────────────────────────────────────────────────────

    def _visualize(self):
        if self._pc is None or len(self._pc) == 0:
            QMessageBox.warning(self, "提示", "暂无点云数据，请先执行扫描重建。")
            return
        try:
            import numpy as np
            import matplotlib
            matplotlib.use('Qt5Agg')
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

            pc = self._pc
            fp = _get_mpl_font()
            tkw = {'fontproperties': fp} if fp else {}

            fig = plt.figure(figsize=(16, 6))
            fig.suptitle("以时间换位深度 — 嵌套叠叠乐 点云", fontsize=14, **tkw)

            # 图1：深度图（热力图）
            ax1 = fig.add_subplot(1, 3, 1)
            if self._depth_map is not None:
                ppmm = pixels_per_mm if pixels_per_mm > 0 else 1.0
                w, h = self._img_size
                ext  = [-w / (2 * ppmm), w / (2 * ppmm),
                         h / (2 * ppmm), -h / (2 * ppmm)]
                im = ax1.imshow(self._depth_map, cmap='plasma', origin='upper', extent=ext)
                plt.colorbar(im, ax=ax1).set_label('Depth (mm)')
                ax1.set_title("Depth Map", **tkw)
                ax1.set_xlabel("X (mm)")
                ax1.set_ylabel("Y (mm)")

            # 图2：锐度图
            ax2 = fig.add_subplot(1, 3, 2)
            if hasattr(self, '_sharp_map') and self._sharp_map is not None:
                im2 = ax2.imshow(
                    np.log1p(self._sharp_map), cmap='hot', origin='upper')
                plt.colorbar(im2, ax=ax2).set_label('log(1+sharpness)')
                ax2.set_title("Sharpness Map (log)", **tkw)

            # 图3：三维点云（降采样）
            ax3 = fig.add_subplot(1, 3, 3, projection='3d')
            x, y, z, iv = pc[:, 0], pc[:, 1], pc[:, 2], pc[:, 3]
            MAX_PTS = 60000
            if len(x) > MAX_PTS:
                idx = np.random.choice(len(x), MAX_PTS, replace=False)
                x, y, z, iv = x[idx], y[idx], z[idx], iv[idx]
            sc = ax3.scatter(x, y, z, c=iv, cmap='gray', s=0.5, alpha=0.6)
            plt.colorbar(sc, ax=ax3, label='Intensity')
            ax3.set_xlabel("X (mm)"); ax3.set_ylabel("Y (mm)"); ax3.set_zlabel("Z (mm)")
            ax3.set_title("Point Cloud ({:,} pts)".format(len(self._pc)), **tkw)

            plt.tight_layout()
            plt.show()
        except ImportError:
            QMessageBox.warning(self, "依赖缺失",
                                "可视化需要 matplotlib:\npip install matplotlib")
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.warning(self, "可视化错误", str(e))

    # ── 导出 ──────────────────────────────────────────────────────

    def _export(self):
        if self._pc is None or len(self._pc) == 0:
            QMessageBox.warning(self, "提示", "暂无点云数据，请先执行扫描重建。")
            return
        default = "temporal_depth_{}.ply".format(
            datetime.now().strftime("%Y%m%d_%H%M%S"))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点云",
            os.path.join(get_effective_save_path(), default),
            "PLY 文件 (*.ply);;CSV 文件 (*.csv);;全部文件 (*.*)")
        if not path:
            return
        try:
            pc = self._pc
            n  = len(pc)
            if path.lower().endswith('.csv'):
                import csv
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerows(
                        [['x_mm', 'y_mm', 'z_mm', 'intensity']] + pc.tolist())
                QMessageBox.information(self, "导出完成",
                                        "已导出 {:,} 个点（CSV）\n{}".format(n, path))
            else:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write("ply\nformat ascii 1.0\n")
                    f.write("comment Generated by BasicDemo TemporalDepth\n")
                    f.write("comment pixels_per_mm={:.4f}\n".format(pixels_per_mm))
                    f.write("element vertex {}\n".format(n))
                    f.write("property float x\nproperty float y\n"
                            "property float z\nproperty float intensity\n")
                    f.write("end_header\n")
                    for row in pc:
                        f.write("{:.6f} {:.6f} {:.6f} {:.2f}\n".format(
                            float(row[0]), float(row[1]), float(row[2]), float(row[3])))
                QMessageBox.information(
                    self, "导出完成",
                    "已导出 {:,} 个点（PLY）\n支持 MeshLab / CloudCompare / Open3D\n{}".format(
                        n, path))
            print("[TemporalDepth] 点云已导出: {}".format(path))
        except Exception as e:
            QMessageBox.warning(self, "导出错误", str(e))


if __name__ == "__main__":

    # ch:初始化SDK | en: initialize SDK
    MvCamera.MV_CC_Initialize()

    global deviceList
    deviceList = MV_CC_DEVICE_INFO_LIST()
    global cam
    cam = MvCamera()
    global nSelCamIndex
    nSelCamIndex = 0
    global obj_cam_operation
    obj_cam_operation = 0
    global isOpen
    isOpen = False
    global isGrabbing
    isGrabbing = False
    global isCalibMode  # 是否是标定模式（获取原始图像）
    isCalibMode = True
    global save_path
    save_path = ""  # 空字符串表示使用脚本所在目录作为默认路径
    global auto_capture_running
    auto_capture_running = False
    global autofocus_running
    autofocus_running = False
    global auto_calib_running
    auto_calib_running = False
    global dark_frame_captured
    dark_frame_captured = False
    global serial_conn
    serial_conn = None
    global is_serial_connected
    is_serial_connected = False
    global pixels_per_mm          # 相机图像像素/mm（比例尺标定值）
    pixels_per_mm = 100.0
    global scale_overlay           # ScaleBarOverlay 实例（setupUi 后创建）
    scale_overlay = None
    global _cam_img_width          # 最近一帧的相机图像宽度（用于显示缩放比）
    _cam_img_width = 0
    global _recon3d_dialog            # 三维重建对话框（单例，懒加载）
    _recon3d_dialog = None
    global _temporal_depth_dialog        # 以时间换位深度对话框（单例，懒加载）
    _temporal_depth_dialog = None

    # 脚本所在目录作为默认保存路径
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    SETTINGS_FILE = os.path.join(SCRIPT_DIR, "setting.ini")

    # 绑定下拉列表至设备信息索引
    def xFunc(event):
        global nSelCamIndex
        nSelCamIndex = TxtWrapBy("[", "]", ui.ComboDevices.get())

    # Decoding Characters
    def decoding_char(ctypes_char_array):
        """
        安全地从 ctypes 字符数组中解码出字符串。
        适用于 Python 2.x 和 3.x，以及 32/64 位环境。
        """
        byte_str = memoryview(ctypes_char_array).tobytes()
        
        # 在第一个空字符处截断
        null_index = byte_str.find(b'\x00')
        if null_index != -1:
            byte_str = byte_str[:null_index]
        
        # 多编码尝试解码
        for encoding in ['gbk', 'utf-8', 'latin-1']:
            try:
                return byte_str.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用替换策略
        return byte_str.decode('latin-1', errors='replace')

    # ch:枚举相机 | en:enum devices
    def enum_devices():
        global deviceList
        global obj_cam_operation

        deviceList = MV_CC_DEVICE_INFO_LIST()
        n_layer_type = (MV_GIGE_DEVICE | MV_USB_DEVICE | MV_GENTL_CAMERALINK_DEVICE
                        | MV_GENTL_CXP_DEVICE | MV_GENTL_XOF_DEVICE)
        ret = MvCamera.MV_CC_EnumDevices(n_layer_type, deviceList)
        if ret != 0:
            strError = "Enum devices fail! ret = :" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            return ret

        if deviceList.nDeviceNum == 0:
            QMessageBox.warning(mainWindow, "Info", "Find no device", QMessageBox.Ok)
            return ret
        print("Find %d devices!" % deviceList.nDeviceNum)

        devList = []
        for i in range(0, deviceList.nDeviceNum):
            mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE or mvcc_dev_info.nTLayerType == MV_GENTL_GIGE_DEVICE:
                print("\ngige device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
                nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
                nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
                nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
                print("current ip: %d.%d.%d.%d " % (nip1, nip2, nip3, nip4))
                devList.append(
                    "[" + str(i) + "]GigE: " + user_defined_name + " " + model_name + "(" + str(nip1) + "." + str(
                        nip2) + "." + str(nip3) + "." + str(nip4) + ")")
            elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                print("\nu3v device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]USB: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_CAMERALINK_DEVICE:
                print("\nCML device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stCMLInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stCMLInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stCMLInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]CML: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_CXP_DEVICE:
                print("\nCXP device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stCXPInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stCXPInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stCXPInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]CXP: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_XOF_DEVICE:
                print("\nXoF device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stXoFInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stXoFInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stXoFInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]XoF: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")

        ui.ComboDevices.clear()
        ui.ComboDevices.addItems(devList)
        ui.ComboDevices.setCurrentIndex(0)

    # ch:打开相机 | en:open device
    def open_device():
        global deviceList
        global nSelCamIndex
        global obj_cam_operation
        global isOpen
        if isOpen:
            QMessageBox.warning(mainWindow, "Error", 'Camera is Running!', QMessageBox.Ok)
            return MV_E_CALLORDER

        nSelCamIndex = ui.ComboDevices.currentIndex()
        if nSelCamIndex < 0:
            QMessageBox.warning(mainWindow, "Error", 'Please select a camera!', QMessageBox.Ok)
            return MV_E_CALLORDER

        obj_cam_operation = CameraOperation(cam, deviceList, nSelCamIndex)
        ret = obj_cam_operation.Open_device()
        if 0 != ret:
            strError = "Open device failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            isOpen = False
        else:
            set_continue_mode()

            get_param()

            isOpen = True
            enable_controls()

    # ch:开始取流 | en:Start grab image
    def start_grabbing():
        global obj_cam_operation
        global isGrabbing

        ret = obj_cam_operation.Start_grabbing(ui.widgetDisplay.winId())
        if ret != 0:
            strError = "Start grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            isGrabbing = True
            enable_controls()
            # 延迟 800ms 后尝试获取图像分辨率，用于比例尺显示缩放
            QTimer.singleShot(800, _poll_cam_img_width)

    # ch:停止取流 | en:Stop grab image
    def stop_grabbing():
        global obj_cam_operation
        global isGrabbing
        ret = obj_cam_operation.Stop_grabbing()
        if ret != 0:
            strError = "Stop grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            isGrabbing = False
            enable_controls()

    # ch:关闭设备 | Close device
    def close_device():
        global isOpen
        global isGrabbing
        global obj_cam_operation

        if isOpen:
            obj_cam_operation.Close_device()
            isOpen = False

        isGrabbing = False

        enable_controls()

    # ch:设置触发模式 | en:set trigger mode
    def set_continue_mode():
        ret = obj_cam_operation.Set_trigger_mode(False)
        if ret != 0:
            strError = "Set continue mode failed ret:" + ToHexStr(ret) + " mode is " + str(is_trigger_mode)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(True)
            ui.radioTriggerMode.setChecked(False)
            ui.bnSoftwareTrigger.setEnabled(False)

    # ch:设置软触发模式 | en:set software trigger mode
    def set_software_trigger_mode():
        ret = obj_cam_operation.Set_trigger_mode(True)
        if ret != 0:
            strError = "Set trigger mode failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(False)
            ui.radioTriggerMode.setChecked(True)
            ui.bnSoftwareTrigger.setEnabled(isGrabbing)

    # ch:设置触发命令 | en:set trigger software
    def trigger_once():
        ret = obj_cam_operation.Trigger_once()
        if ret != 0:
            strError = "TriggerSoftware failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)

    # ch:存图 | en:save image
    def save_bmp():
        ret = obj_cam_operation.Save_Bmp()
        if ret != MV_OK:
            strError = "Save BMP failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            print("Save image success")

    # ---- 设置读写 ----
    def load_settings():
        """从 setting.ini 读取保存路径、串口设置及比例尺标定值"""
        global save_path, pixels_per_mm
        config = configparser.ConfigParser()
        if os.path.exists(SETTINGS_FILE):
            config.read(SETTINGS_FILE, encoding='utf-8')
            save_path = config.get('Settings', 'save_path', fallback='')
            saved_baud    = config.get('Serial', 'baud_rate', fallback='115200')
            saved_timeout = config.get('Serial', 'timeout',   fallback='1.0')
            saved_port    = config.get('Serial', 'port',      fallback='')
            try:
                pixels_per_mm = float(config.get('Scale', 'pixels_per_mm', fallback='100.0'))
                if pixels_per_mm <= 0:
                    pixels_per_mm = 100.0
            except ValueError:
                pixels_per_mm = 100.0
        else:
            save_path     = ''
            saved_baud    = '115200'
            saved_timeout = '1.0'
            saved_port    = ''
            pixels_per_mm = 100.0
        _update_path_label()
        # 填充波特率下拉列表
        baud_rates = ['9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600']
        ui.cmbBaudRate.clear()
        ui.cmbBaudRate.addItems(baud_rates)
        idx = ui.cmbBaudRate.findText(saved_baud)
        ui.cmbBaudRate.setCurrentIndex(idx if idx >= 0 else baud_rates.index('115200'))
        # 填充超时
        ui.edtSerialTimeout.setText(saved_timeout)
        # 初始化可用串口并尝试恢复上次选择
        refresh_serial_ports()
        if saved_port:
            idx_port = ui.cmbSerialPort.findText(saved_port)
            if idx_port >= 0:
                ui.cmbSerialPort.setCurrentIndex(idx_port)
        _update_serial_status()
        # 恢复比例尺标定值到 UI
        ui.edtPixelsPerMm.setText("{:.4f}".format(pixels_per_mm))
        scale_overlay.set_pixels_per_mm(pixels_per_mm)
        _update_scale_info_label()
        print("Settings loaded. Save path: '{}'".format(save_path or SCRIPT_DIR))

    def save_settings():
        """将保存路径、串口设置及比例尺标定值写入 setting.ini"""
        config = configparser.ConfigParser()
        config['Settings'] = {'save_path': save_path}
        config['Serial'] = {
            'port':      ui.cmbSerialPort.currentText() if ui.cmbSerialPort.count() > 0 else '',
            'baud_rate': ui.cmbBaudRate.currentText(),
            'timeout':   ui.edtSerialTimeout.text().strip(),
        }
        config['Scale'] = {
            'pixels_per_mm': str(pixels_per_mm),
        }
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        print("Settings saved. Save path: '{}'".format(save_path))

    def _update_path_label():
        """刷新界面上的路径提示标签"""
        effective = save_path if save_path else SCRIPT_DIR
        ui.lblSavePathInfo.setText("保存至: " + effective)

    def get_effective_save_path():
        """返回实际使用的保存目录"""
        return save_path if save_path else SCRIPT_DIR

    def set_save_path():
        """打开文件夹选择对话框，保存选中路径到 setting.ini"""
        global save_path
        new_path = QFileDialog.getExistingDirectory(
            mainWindow, "选择图片保存路径", get_effective_save_path())
        if new_path:
            save_path = new_path
            save_settings()
            _update_path_label()

    # ---- 自动拍摄 ----
    def _auto_capture_worker(count):
        """后台线程：连续拍摄 count 张图片并保存"""
        global auto_capture_running
        save_dir = get_effective_save_path()
        os.makedirs(save_dir, exist_ok=True)
        success_count = 0
        timestamp_base = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i in range(count):
            if not auto_capture_running:
                break
            file_name = "{}_{:03d}.bmp".format(timestamp_base, i + 1)
            full_path = os.path.join(save_dir, file_name)
            try:
                ret = obj_cam_operation.Save_Bmp_with_path(full_path)
                if ret == MV_OK:
                    success_count += 1
                    print("Auto capture [{}/{}]: {}".format(i + 1, count, full_path))
                else:
                    print("Auto capture [{}/{}] failed, ret: {}".format(
                        i + 1, count, ToHexStr(ret)))
            except Exception as e:
                print("Auto capture [{}/{}] error: {}".format(i + 1, count, str(e)))
            # 等待一小段时间以获取不同帧
            time.sleep(0.2)

        auto_capture_running = False
        msg = "自动拍摄完成！成功保存 {}/{} 张图片\n保存路径: {}".format(
            success_count, count, save_dir)
        QTimer.singleShot(0, lambda: QMessageBox.information(mainWindow, "完成", msg))

    def start_auto_capture():
        """检查输入并启动自动拍摄线程"""
        global auto_capture_running
        if auto_capture_running:
            QMessageBox.warning(mainWindow, "提示", "自动拍摄正在进行中！", QMessageBox.Ok)
            return
        count_str = ui.edtCaptureCount.text().strip()
        if not count_str.isdigit() or int(count_str) <= 0:
            QMessageBox.warning(mainWindow, "错误", "请输入正整数！", QMessageBox.Ok)
            return
        count = int(count_str)
        auto_capture_running = True
        t = threading.Thread(target=_auto_capture_worker, args=(count,), daemon=True)
        t.start()

    def is_float(str):
        try:
            float(str)
            return True
        except ValueError:
            return False

    # ---- 自动对焦（对比度解析 + 混合PID）----
    def _compute_sharpness():
        """计算当前帧的锏度分数：拉普拉斯方差 + Tenengrad 加权平均"""
        try:
            import numpy as np
            data, w, h = obj_cam_operation.Get_frame_numpy()
            if data is None or w == 0 or h == 0:
                return 0.0
            # 只取前 w*h 字节（Mono8 / Bayer8 均适用）
            if len(data) < w * h:
                return 0.0
            gray = data[:w * h].reshape(h, w).astype(np.float32)
            # Tenengrad（简化 Sobel）
            dx = gray[:, 1:] - gray[:, :-1]
            dy = gray[1:, :] - gray[:-1, :]
            tenengrad = float(np.mean(dx ** 2) + np.mean(dy ** 2))
            # 拉普拉斯方差
            lap = (gray[:-2, 1:-1] + gray[2:, 1:-1] +
                   gray[1:-1, :-2] + gray[1:-1, 2:] -
                   4 * gray[1:-1, 1:-1])
            lap_var = float(np.var(lap))
            return 0.5 * tenengrad + 0.5 * lap_var
        except Exception as e:
            print("[AF] 锏度计算异常:", e)
            return 0.0

    def _af_move_z(step_mm):
        """相对移动 Z 轴 step_mm 毫米，返回是否成功"""
        if not send_gcode("G91\n"):
            return False
        if not send_gcode("G1 Z{:.4f} F300\n".format(step_mm)):
            return False
        if not send_gcode("G90\n"):
            return False
        time.sleep(0.25)
        return True

    def _autofocus_worker():
        """
        自动对焦后台线程：
          Phase 1 — 粗搜索：大步长扫描找到大致最优位置
          Phase 2 — 中等精度搜索：缩小范围细化
          Phase 3 — 混合 PID：寻找锏度梯度为零的位置
        """
        global autofocus_running

        def set_status(msg):
            QTimer.singleShot(0, lambda: ui.lblAutoFocusStatus.setText(msg))

        try:
            set_status("对焦中… 粗搜索")
            print("[AF] ===== 开始自动对焦 =====")

            # ----------------------------------------
            # Phase 1: 粗搜索  ±3mm 步长 1mm
            # ----------------------------------------
            COARSE_STEP = 1.0
            COARSE_HALF = 3
            current_pos = 0.0

            if not _af_move_z(-COARSE_STEP * COARSE_HALF):
                set_status("对焦失败：串口错误")
                return
            current_pos = -COARSE_STEP * COARSE_HALF

            scores_c, pos_c = [], []
            total_c = COARSE_HALF * 2 + 1
            for i in range(total_c):
                if not autofocus_running:
                    set_status("已停止")
                    return
                time.sleep(0.15)
                s = _compute_sharpness()
                scores_c.append(s)
                pos_c.append(current_pos)
                print("[AF]粗搜索 pos={:.1f}mm s={:.1f}".format(current_pos, s))
                set_status("对焦中… 粗搜索 {}/{}".format(i + 1, total_c))
                if i < total_c - 1:
                    _af_move_z(COARSE_STEP)
                    current_pos += COARSE_STEP

            best_c = int(max(range(len(scores_c)), key=lambda k: scores_c[k]))
            best_pos = pos_c[best_c]
            print("[AF]粗搜索最佳: {:.1f}mm  s={:.1f}".format(best_pos, scores_c[best_c]))
            _af_move_z(best_pos - current_pos)
            current_pos = best_pos

            # ----------------------------------------
            # Phase 2: 中等搜索  ±0.8mm 步长 0.2mm
            # ----------------------------------------
            set_status("对焦中… 中等搜索")
            MEDIUM_STEP = 0.2
            MEDIUM_HALF = 4
            _af_move_z(-MEDIUM_STEP * MEDIUM_HALF)
            current_pos -= MEDIUM_STEP * MEDIUM_HALF

            scores_m, pos_m = [], []
            total_m = MEDIUM_HALF * 2 + 1
            for i in range(total_m):
                if not autofocus_running:
                    set_status("已停止")
                    return
                time.sleep(0.12)
                s = _compute_sharpness()
                scores_m.append(s)
                pos_m.append(current_pos)
                print("[AF]中等搜索 pos={:.2f}mm s={:.1f}".format(current_pos, s))
                set_status("对焦中… 中等搜索 {}/{}".format(i + 1, total_m))
                if i < total_m - 1:
                    _af_move_z(MEDIUM_STEP)
                    current_pos += MEDIUM_STEP

            best_m = int(max(range(len(scores_m)), key=lambda k: scores_m[k]))
            best_pos = pos_m[best_m]
            print("[AF]中等搜索最佳: {:.2f}mm  s={:.1f}".format(best_pos, scores_m[best_m]))
            _af_move_z(best_pos - current_pos)
            current_pos = best_pos

            # ----------------------------------------
            # Phase 3: 混合 PID 精细调节
            #  误差 = 锏度梯度（如在最佳点，梯度=0）
            # ----------------------------------------
            set_status("对焦中… PID 精细")
            print("[AF] PID 精细开始")
            Kp, Ki, Kd = 0.06, 0.004, 0.018
            integral = 0.0
            prev_error = 0.0
            PROBE = 0.05        # 探测步长 mm
            MAX_ITER = 20
            CONV_THR = 0.004    # 步长小于此值则认为收敛

            for it in range(MAX_ITER):
                if not autofocus_running:
                    break
                # 正向探测
                _af_move_z(PROBE)
                current_pos += PROBE
                time.sleep(0.1)
                s_plus = _compute_sharpness()
                # 负向探测
                _af_move_z(-2 * PROBE)
                current_pos -= 2 * PROBE
                time.sleep(0.1)
                s_minus = _compute_sharpness()
                # 回到中间
                _af_move_z(PROBE)
                current_pos += PROBE

                gradient = (s_plus - s_minus) / (2 * PROBE)
                error = gradient
                integral = max(-0.5, min(0.5, integral + error * 0.01))
                derivative = error - prev_error
                control = Kp * error + Ki * integral + Kd * derivative
                step = max(-0.15, min(0.15, control))
                print("[AF] PID迭 {}: grad={:.1f} step={:.4f}mm".format(it + 1, gradient, step))

                prev_error = error
                if abs(step) < CONV_THR:
                    print("[AF] PID 收敛!")
                    break
                _af_move_z(step)
                current_pos += step

            s_final = _compute_sharpness()
            print("[AF] ===== 对焦完成 最终锏度={:.1f} =====".format(s_final))
            set_status("对焦完成 \u2713  锏度:{:.0f}".format(s_final))

        except Exception as e:
            print("[AF] 异常:", e)
            set_status("对焦失败: " + str(e))
        finally:
            autofocus_running = False
            QTimer.singleShot(0, lambda: ui.bnAutoFocus.setEnabled(True))
            QTimer.singleShot(0, lambda: ui.bnStopAutoFocus.setEnabled(False))

    def start_autofocus():
        """启动自动对焦线程"""
        global autofocus_running
        if not is_serial_connected:
            QMessageBox.warning(mainWindow, "错误", "请先连接串口！", QMessageBox.Ok)
            return
        if autofocus_running:
            QMessageBox.warning(mainWindow, "提示", "对焦正在进行！", QMessageBox.Ok)
            return
        autofocus_running = True
        ui.bnAutoFocus.setEnabled(False)
        ui.bnStopAutoFocus.setEnabled(True)
        t = threading.Thread(target=_autofocus_worker, daemon=True)
        t.start()

    def stop_autofocus():
        """请求停止对焦"""
        global autofocus_running
        autofocus_running = False
        ui.lblAutoFocusStatus.setText("停止中…")

    def refresh_serial_ports():
        """扫描系统可用串口并刷新下拉列表"""
        if not _SERIAL_AVAILABLE:
            ui.cmbSerialPort.clear()
            ui.cmbSerialPort.addItem("pyserial 未安装")
            return
        current = ui.cmbSerialPort.currentText()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        ui.cmbSerialPort.clear()
        if ports:
            ui.cmbSerialPort.addItems(ports)
            idx = ui.cmbSerialPort.findText(current)
            if idx >= 0:
                ui.cmbSerialPort.setCurrentIndex(idx)
        else:
            ui.cmbSerialPort.addItem("无可用串口")
        print("已刷新串口列表: {}".format(ports if ports else "无"))

    def _update_serial_status():
        """根据连接状态更新状态标签样式"""
        if is_serial_connected:
            ui.lblSerialStatus.setText("● 已连接")
            ui.lblSerialStatus.setStyleSheet("color: green; font-weight: bold;")
            ui.bnConnectSerial.setText("断开串口")
        else:
            ui.lblSerialStatus.setText("● 未连接")
            ui.lblSerialStatus.setStyleSheet("color: red; font-weight: bold;")
            ui.bnConnectSerial.setText("连接串口")

    def connect_serial():
        """切换串口连接状态（连接/断开）"""
        global serial_conn, is_serial_connected
        if not _SERIAL_AVAILABLE:
            QMessageBox.warning(mainWindow, "错误",
                                "pyserial 未安装，请执行:\npip install pyserial",
                                QMessageBox.Ok)
            return

        if is_serial_connected:
            # 断开连接
            try:
                serial_conn.close()
            except Exception:
                pass
            serial_conn = None
            is_serial_connected = False
            _update_serial_status()
            save_settings()
            print("串口已断开")
        else:
            # 建立连接
            port = ui.cmbSerialPort.currentText()
            if not port or port in ("无可用串口", "pyserial 未安装"):
                QMessageBox.warning(mainWindow, "错误",
                                    "请先选择有效的串口！", QMessageBox.Ok)
                return
            baud_str    = ui.cmbBaudRate.currentText()
            timeout_str = ui.edtSerialTimeout.text().strip()
            try:
                baud = int(baud_str)
            except ValueError:
                QMessageBox.warning(mainWindow, "错误", "波特率格式不正确！", QMessageBox.Ok)
                return
            try:
                timeout = float(timeout_str)
            except ValueError:
                QMessageBox.warning(mainWindow, "错误",
                                    "超时时间格式不正确，请输入数字！", QMessageBox.Ok)
                return
            try:
                serial_conn = serial.Serial(
                    port=port,
                    baudrate=baud,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=timeout
                )
                is_serial_connected = True
                _update_serial_status()
                save_settings()
                print("串口已连接: {} @ {} baud, timeout={}s".format(port, baud, timeout))
            except serial.SerialException as e:
                QMessageBox.warning(mainWindow, "串口错误",
                                    "无法打开串口:\n" + str(e), QMessageBox.Ok)

    # ---- G-code 发送 ----
    def send_gcode(cmd):
        """通用 G-code 发送函数：检查连接状态后将命令编码发送至串口"""
        if not is_serial_connected or serial_conn is None:
            QMessageBox.warning(mainWindow, "错误",
                                "串口未连接，请先连接串口！", QMessageBox.Ok)
            return False
        try:
            serial_conn.write(cmd.encode('utf-8'))
            print("已发送 G-code: {}".format(cmd.strip()))
            return True
        except Exception as e:
            QMessageBox.warning(mainWindow, "串口错误",
                                "发送失败:\n" + str(e), QMessageBox.Ok)
            return False

    def action_home_z():
        """Z 轴归零：发送 G28 Z"""
        send_gcode("G28 Z\n")

    def action_move_z_step():
        """Z 轴微调（相对运动 0.1mm）"""
        if send_gcode("G91\n"):
            send_gcode("G1 Z0.1 F300\n")
            send_gcode("G90\n")

    def action_set_light():
        """亮度控制（PWM）：读取 edtLightValue 并发送 M106 S{value}"""
        value_str = ui.edtLightValue.text().strip()
        if not value_str.isdigit():
            QMessageBox.warning(mainWindow, "错误",
                                "请输入 0-255 之间的整数！", QMessageBox.Ok)
            return
        value = int(value_str)
        if not (0 <= value <= 255):
            QMessageBox.warning(mainWindow, "错误",
                                "亮度值必须在 0-255 范围内！", QMessageBox.Ok)
            return
        send_gcode("M106 S{}\n".format(value))

    # ── 比例尺功能 ────────────────────────────────────────────────

    def _poll_cam_img_width():
        """采集开始后单次轮询，获取相机图像宽度供比例尺缩放使用。"""
        global _cam_img_width
        if obj_cam_operation and isGrabbing:
            try:
                _, w, _h = obj_cam_operation.Get_frame_numpy()
                if w > 0:
                    _cam_img_width = w
                    scale_overlay.set_img_width(w)
            except Exception:
                pass

    def _apply_scale_calib():
        """读取 edtPixelsPerMm 输入，更新标定值并刷新叠加层。"""
        global pixels_per_mm, _cam_img_width
        try:
            v = float(ui.edtPixelsPerMm.text().strip())
            if v <= 0.0:
                raise ValueError("非正数")
        except ValueError:
            QMessageBox.warning(mainWindow, "输入错误",
                                "请输入有效的正数（像素/mm）。", QMessageBox.Ok)
            return
        pixels_per_mm = v
        # 尝试获取当前帧图像宽度（用于计算显示缩放系数）
        if obj_cam_operation and isGrabbing:
            try:
                _, w, _h = obj_cam_operation.Get_frame_numpy()
                if w > 0:
                    _cam_img_width = w
                    scale_overlay.set_img_width(w)
            except Exception:
                pass
        scale_overlay.set_pixels_per_mm(pixels_per_mm)
        _update_scale_info_label()
        save_settings()

    def _toggle_scale_bar(state):
        """复选框状态变化时切换叠加层可见性。"""
        scale_overlay.set_visible(state == Qt.Checked)

    def _update_scale_info_label():
        """刷新状态标签：显示 1mm 对应像素数及每像素微米数。"""
        if scale_overlay is None or pixels_per_mm <= 0:
            ui.lblScaleBarInfo.setText("未标定")
            return
        info = "1mm={:.1f}px | {:.3f}µm/px".format(
            pixels_per_mm, 1000.0 / pixels_per_mm)
        ui.lblScaleBarInfo.setText(info)

    # ── 自动标定 ─────────────────────────────────────────────────

    def _phase_correlation_shift(frame1, frame2):
        """
        使用相位相关法计算两帧之间的亚像素位移幅度。
        返回 (dx, dy)：正值表示帧2相对帧1在对应方向的位移（像素）。
        若无法计算则返回 (0.0, 0.0)。
        """
        try:
            import numpy as np
            f1 = frame1.astype(np.float64) - np.mean(frame1)
            f2 = frame2.astype(np.float64) - np.mean(frame2)
            F1 = np.fft.fft2(f1)
            F2 = np.fft.fft2(f2)
            # 归一化互功率谱
            R = F1 * np.conj(F2)
            eps = np.abs(R).max() * 1e-10 + 1e-30
            R = R / (np.abs(R) + eps)
            # 逆变换并找峰值
            r = np.fft.ifft2(R).real
            idx = np.unravel_index(np.argmax(r), r.shape)
            dy, dx = int(idx[0]), int(idx[1])
            h, w = frame1.shape[:2]
            # 处理环绕（移位量 > 图像半边）
            if dy > h // 2:
                dy -= h
            if dx > w // 2:
                dx -= w
            return float(dx), float(dy)
        except Exception as e:
            print("[AutoCalib] 相位相关异常:", e)
            return 0.0, 0.0

    def _auto_calib_worker(move_mm, axis):
        """
        自动标定后台线程：
          1. 采集初始帧
          2. 沿指定轴移动已知距离
          3. 采集移动后帧
          4. 用相位相关计算像素位移
          5. pixels_per_mm = |位移| / move_mm，更新标定值
        axis: 'X' 或 'Y'，决定使用 dx 还是 dy
        """
        global auto_calib_running

        def set_status(msg):
            QTimer.singleShot(0, lambda m=msg: ui.lblAutoCalibStatus.setText(m))

        try:
            import numpy as np

            # ── 帧1 ──
            set_status("标定中… 采集初始帧")
            print("[AutoCalib] 采集帧1")
            data1, w, h = obj_cam_operation.Get_frame_numpy()
            if data1 is None or w == 0 or h == 0 or len(data1) < w * h:
                set_status("标定失败：无法获取初始帧")
                return
            frame1 = data1[:w * h].reshape(h, w).astype(np.float32)

            # ── 移动已知距离 ──
            set_status("标定中… 移动 {:.3f}mm ({})轴".format(move_mm, axis))
            print("[AutoCalib] 移动 {}轴 {:.3f}mm".format(axis, move_mm))
            if not send_gcode("G91\n"):
                set_status("标定失败：串口错误（G91）")
                return
            if not send_gcode("G1 {}{:.4f} F300\n".format(axis, move_mm)):
                set_status("标定失败：串口错误（移动）")
                return
            if not send_gcode("G90\n"):
                set_status("标定失败：串口错误（G90）")
                return
            # 等待运动完成（依据距离动态估算）
            wait_s = max(0.5, abs(move_mm) / 10.0 + 0.4)
            time.sleep(wait_s)

            # ── 帧2 ──
            set_status("标定中… 采集移动后帧")
            print("[AutoCalib] 采集帧2")
            data2, w2, h2 = obj_cam_operation.Get_frame_numpy()
            if data2 is None or w2 == 0 or h2 == 0 or len(data2) < w2 * h2:
                set_status("标定失败：无法获取移动后帧")
                return
            frame2 = data2[:w2 * h2].reshape(h2, w2).astype(np.float32)

            # ── 相位相关 ──
            set_status("标定中… 计算像素位移")
            dx, dy = _phase_correlation_shift(frame1, frame2)
            shift_px = abs(dx) if axis.upper() == 'X' else abs(dy)
            print("[AutoCalib] dx={:.2f}px  dy={:.2f}px  使用{}方向={:.2f}px".format(
                dx, dy, axis, shift_px))

            if shift_px < 1.0:
                set_status("标定失败：位移过小({:.2f}px)\n请增大移动距离或确保视野有纹理".format(shift_px))
                return

            # ── 计算并更新 pixels/mm ──
            ppmm = shift_px / abs(move_mm)
            print("[AutoCalib] pixels/mm = {:.4f}".format(ppmm))

            def _update_ui():
                global pixels_per_mm
                pixels_per_mm = ppmm
                ui.edtPixelsPerMm.setText("{:.4f}".format(ppmm))
                _apply_scale_calib()
                ui.lblAutoCalibStatus.setText(
                    "标定完成 ✓\n{:.2f} px/mm | {:.3f} µm/px".format(
                        ppmm, 1000.0 / ppmm))
            QTimer.singleShot(0, _update_ui)

        except Exception as e:
            print("[AutoCalib] 异常:", e)
            set_status("标定失败: " + str(e))
        finally:
            auto_calib_running = False
            QTimer.singleShot(0, lambda: ui.bnAutoCalib.setEnabled(True))

    # ── 底噪扣除 ──────────────────────────────────────────────

    def capture_dark_frame():
        """采集当前帧作为底噪（暗帧），存入 obj_cam_operation.dark_frame"""
        global dark_frame_captured
        if not isGrabbing:
            QMessageBox.warning(mainWindow, "错误", "请先开始采集！", QMessageBox.Ok)
            return
        try:
            import numpy as np
            data, w, h = obj_cam_operation.Get_frame_numpy()
            if data is None or w == 0 or h == 0:
                QMessageBox.warning(mainWindow, "错误",
                                    "无法获取当前帧，请确认相机正在输出图像。",
                                    QMessageBox.Ok)
                return
            frame_len = w * h  # Mono8/Bayer8
            if len(data) < frame_len:
                QMessageBox.warning(mainWindow, "错误",
                                    "帧数据长度不匹配（{} < {}*{}）。".format(
                                        len(data), w, h), QMessageBox.Ok)
                return
            # 取前 w*h 字节（支持 Mono8 / BayerXX8）
            dark = data[:frame_len].astype(np.int16)
            # 存入完整帧长度（SDK 帧长度可能包含额外对齐字节）
            full_dark = data.astype(np.int16)   # 长度 = nFrameLen
            obj_cam_operation.dark_frame = full_dark
            dark_frame_captured = True
            ui.chkDarkSub.setEnabled(True)
            ui.bnClearDark.setEnabled(True)
            mean_val = float(np.mean(dark))
            ui.lblDarkSubStatus.setText(
                "帧大小: {}x{}\n均值: {:.1f}\n底噪帧已就绪".format(w, h, mean_val))
            print("[DarkSub] 底噪帧已采集: {}x{}, 均值={:.1f}".format(w, h, mean_val))
        except Exception as e:
            print("[DarkSub] 采集异常:", e)
            QMessageBox.warning(mainWindow, "错误",
                                "采集底噪帧失败:\n" + str(e), QMessageBox.Ok)

    def toggle_dark_sub(state):
        """复选框状态变化时切换底噪扣除开关"""
        if obj_cam_operation and isGrabbing:
            enabled = (state == Qt.Checked)
            obj_cam_operation.apply_dark_sub = enabled
            _update_dark_sub_status_label(dark_frame_captured, enabled)
            print("[DarkSub] 底噪扣除{}".format("已启用" if enabled else "已禁用"))
    def _update_dark_sub_status_label(captured, enabled):
        """^统一刷新底噪状态标签"""
        if not captured:
            ui.lblDarkSubStatus.setText("未采集")
        elif enabled:
            ui.lblDarkSubStatus.setText("底噪帧已就绪\n已开启 ✔")
        else:
            ui.lblDarkSubStatus.setText("底噪帧已就绪\n未开启")

    def clear_dark_frame():
        """清除底噪帧并禁用扣除"""
        global dark_frame_captured
        if obj_cam_operation:
            obj_cam_operation.dark_frame = None
            obj_cam_operation.apply_dark_sub = False
        dark_frame_captured = False
        ui.chkDarkSub.setChecked(False)
        ui.chkDarkSub.setEnabled(False)
        ui.bnClearDark.setEnabled(False)
        ui.lblDarkSubStatus.setText("未采集")
        print("[DarkSub] 底噪帧已清除")

    def start_auto_calib():
        """读取 UI 输入并启动自动标定线程"""
        global auto_calib_running
        if not isGrabbing:
            QMessageBox.warning(mainWindow, "错误", "请先开始采集！", QMessageBox.Ok)
            return
        if not is_serial_connected:
            QMessageBox.warning(mainWindow, "错误", "请先连接串口！", QMessageBox.Ok)
            return
        if auto_calib_running:
            QMessageBox.warning(mainWindow, "提示", "标定正在进行中！", QMessageBox.Ok)
            return
        move_str = ui.edtCalibMoveMm.text().strip()
        try:
            move_mm = float(move_str)
            if abs(move_mm) < 0.01:
                raise ValueError("移动量过小")
        except ValueError:
            QMessageBox.warning(mainWindow, "输入错误",
                                "请输入有效的移动距离（mm），最小 0.01mm。",
                                QMessageBox.Ok)
            return
        # 询问标定轴
        axis, ok = QInputDialog.getItem(
            mainWindow, "选择标定轴",
            "请选择移动轴（相机水平方向通常对应 X）：",
            ["X", "Y"], 0, False)
        if not ok:
            return
        auto_calib_running = True
        ui.bnAutoCalib.setEnabled(False)
        ui.lblAutoCalibStatus.setText("标定中…")
        t = threading.Thread(
            target=_auto_calib_worker, args=(move_mm, axis), daemon=True)
        t.start()

    def get_param():
        ret = obj_cam_operation.Get_parameter()
        if ret != MV_OK:
            strError = "Get param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.edtExposureTime.setText("{0:.2f}".format(obj_cam_operation.exposure_time))
            ui.edtGain.setText("{0:.2f}".format(obj_cam_operation.gain))
            ui.edtFrameRate.setText("{0:.2f}".format(obj_cam_operation.frame_rate))

    # ch: 设置参数 | en:set param
    def set_param():
        frame_rate = ui.edtFrameRate.text()
        exposure = ui.edtExposureTime.text()
        gain = ui.edtGain.text()

        if is_float(frame_rate)!=True or is_float(exposure)!=True or is_float(gain)!=True:
            strError = "Set param failed ret:" + ToHexStr(MV_E_PARAMETER)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            return MV_E_PARAMETER
        
        ret = obj_cam_operation.Set_parameter(frame_rate, exposure, gain)
        if ret != MV_OK:
            strError = "Set param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)

        return MV_OK

    # ch: 设置控件状态 | en:set enable status
    def enable_controls():
        global isGrabbing
        global isOpen

        # 先设置group的状态，再单独设置各控件状态
        ui.groupGrab.setEnabled(isOpen)
        ui.groupParam.setEnabled(isOpen)

        ui.bnOpen.setEnabled(not isOpen)
        ui.bnClose.setEnabled(isOpen)

        ui.bnStart.setEnabled(isOpen and (not isGrabbing))
        ui.bnStop.setEnabled(isOpen and isGrabbing)
        ui.bnSoftwareTrigger.setEnabled(isGrabbing and ui.radioTriggerMode.isChecked())

        ui.bnSaveImage.setEnabled(isOpen and isGrabbing)
        ui.bnAutoCapture.setEnabled(isOpen and isGrabbing)
        ui.bnAutoFocus.setEnabled(isOpen and isGrabbing and not autofocus_running)
        ui.bnStopAutoFocus.setEnabled(autofocus_running)
        ui.bnAutoCalib.setEnabled(isOpen and isGrabbing and not auto_calib_running)
        ui.bnCaptureDark.setEnabled(isOpen and isGrabbing)
        if not (isOpen and isGrabbing):
            # 停止采集时同时禁用扣除，但保留已采集帧的按钮状态
            if obj_cam_operation:
                obj_cam_operation.apply_dark_sub = False
            ui.chkDarkSub.setChecked(False)

    # ch: 初始化app, 绑定控件与函数 | en: Init app, bind ui and api
    app = QApplication(sys.argv)
    mainWindow = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(mainWindow)

    # 创建比例尺叠加层（必须在 setupUi 之后，widgetDisplay 已存在）
    scale_overlay = ScaleBarOverlay(ui.widgetDisplay)
    _resize_filter = _ResizeFilter(scale_overlay)
    ui.widgetDisplay.installEventFilter(_resize_filter)

    ui.bnEnum.clicked.connect(enum_devices)
    ui.bnOpen.clicked.connect(open_device)
    ui.bnClose.clicked.connect(close_device)
    ui.bnStart.clicked.connect(start_grabbing)
    ui.bnStop.clicked.connect(stop_grabbing)

    ui.bnSoftwareTrigger.clicked.connect(trigger_once)
    ui.radioTriggerMode.clicked.connect(set_software_trigger_mode)
    ui.radioContinueMode.clicked.connect(set_continue_mode)

    ui.bnGetParam.clicked.connect(get_param)
    ui.bnSetParam.clicked.connect(set_param)

    ui.bnSaveImage.clicked.connect(save_bmp)
    ui.bnAutoCapture.clicked.connect(start_auto_capture)
    ui.bnSetSavePath.clicked.connect(set_save_path)
    ui.bnAutoFocus.clicked.connect(start_autofocus)
    ui.bnStopAutoFocus.clicked.connect(stop_autofocus)
    ui.bnRefreshPort.clicked.connect(refresh_serial_ports)
    ui.bnConnectSerial.clicked.connect(connect_serial)
    ui.bnHomeZ.clicked.connect(action_home_z)
    ui.bnMoveStep.clicked.connect(action_move_z_step)
    ui.bnSetLight.clicked.connect(action_set_light)
    ui.bnSetScaleCalib.clicked.connect(_apply_scale_calib)
    ui.bnAutoCalib.clicked.connect(start_auto_calib)

    # ── 三维重建菜单 ──────────────────────────────────────────────────
    def open_recon3d_dialog():
        """打开（或激活已存在的）三维重建对话框"""
        global _recon3d_dialog
        if _recon3d_dialog is None:
            _recon3d_dialog = PointCloudReconDialog(mainWindow)
        _recon3d_dialog.show()
        _recon3d_dialog.raise_()
        _recon3d_dialog.activateWindow()

    def open_temporal_depth_dialog():
        """打开（或激活已存在的）以时间换位深度对话框"""
        global _temporal_depth_dialog
        if _temporal_depth_dialog is None:
            _temporal_depth_dialog = TemporalDepthDialog(mainWindow)
        _temporal_depth_dialog.show()
        _temporal_depth_dialog.raise_()
        _temporal_depth_dialog.activateWindow()

    menubar = mainWindow.menuBar()
    menu_recon = menubar.addMenu("三维重建(&3D)")
    act_open_recon = menu_recon.addAction("① 停-拍-移 点云重建（DFF）…")
    act_open_recon.setToolTip("Z 轴逐步停顿采集，基于深度从焦点算法重建三维点云")
    act_open_recon.triggered.connect(open_recon3d_dialog)
    act_temporal = menu_recon.addAction("② 以时间换位深度（嵌套叠叠乐）…")
    act_temporal.setToolTip("Z 轴匀速连续扫描 + 时间映射 Z 位置 + 嵌套精扫融合")
    act_temporal.triggered.connect(open_temporal_depth_dialog)
    menu_recon.addSeparator()
    act_help = menu_recon.addAction("使用说明")
    act_help.triggered.connect(lambda: QMessageBox.information(
        mainWindow, "三维重建使用说明",
        "══════════════════════════════════════\n"
        "① 停-拍-移 点云重建（DFF）\n"
        "══════════════════════════════════════\n"
        "原理：Z 轴逐步停顿 → 每步拍一帧 → 逐像素取锐度最大 Z 值\n\n"
        "适用：高精度场景，Z 轴定位准确，场景静止\n"
        "缺点：速度慢（每步需等待运动稳定）\n\n"
        "使用步骤：\n"
        "  1. 开启相机采集  2. 连接串口\n"
        "  3. 设置好 pixels/mm  4. 设置 Z 范围和步长\n"
        "  5. 点击「开始重建」  6. 可视化/导出点云\n\n"
        "══════════════════════════════════════\n"
        "② 以时间换位深度（嵌套叠叠乐）\n"
        "══════════════════════════════════════\n"
        "原理：Z 轴匀速连续扫描，相机同步按时间间隔采帧，\n"
        "      每帧 Z 位置由 z(t)=z₀+speed×t 推算，\n"
        "      可选「嵌套精扫」—— 粗扫后自动定位最佳焦深区间，\n"
        "      再以更低速度细扫并与粗扫数据融合（叠叠乐）。\n\n"
        "优点：Z 轴无需停顿，采帧效率高；嵌套融合逐步提升精度\n"
        "缺点：依赖 Z 轴匀速精度（开环时间估算）\n\n"
        "使用步骤：\n"
        "  1. 开启相机采集（串口连接可选，无串口时 Z 不动）\n"
        "  2. 设置 Z 范围、扫描速度、采帧间隔\n"
        "  3. 勾选「嵌套精扫」并配置精扫参数\n"
        "  4. 点击「开始扫描」，等待粗扫 + 精扫完成\n"
        "  5. 查看日志了解叠叠乐融合结果\n"
        "  6. 可视化深度图/锐度图/点云，或导出 .ply/.csv\n\n"
        "两种模式均可导出 .ply 文件，\n"
        "支持 MeshLab / CloudCompare / Open3D 打开"))
    ui.bnCaptureDark.clicked.connect(capture_dark_frame)
    ui.chkDarkSub.stateChanged.connect(toggle_dark_sub)
    ui.bnClearDark.clicked.connect(clear_dark_frame)
    ui.chkShowScaleBar.stateChanged.connect(_toggle_scale_bar)

    load_settings()
    mainWindow.show()

    app.exec_()

    close_device()

    # 关闭串口
    if is_serial_connected and serial_conn is not None:
        try:
            serial_conn.close()
            print("退出时已自动关闭串口")
        except Exception:
            pass

    # ch:反初始化SDK | en: finalize SDK
    MvCamera.MV_CC_Finalize()

    sys.exit()
    
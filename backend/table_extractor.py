import cv2
import numpy as np
import pandas as pd
from paddleocr import PaddleOCR
import logging
import os
from typing import List, Optional
import json

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TableExtractor:
    """表格提取器"""

    def __init__(self, use_gpu: bool = False):
        """
        初始化 OCR 引擎

        Args:
            use_gpu: 是否使用 GPU
        """
        try:
            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang='ch',
                table=True,  # 启用表格识别
                use_gpu=use_gpu,
                show_log=False,
                det_db_box_thresh=0.5,
                det_db_unclip_ratio=1.6,
                rec_char_dict_path=None,
                table_char_dict_path=None
            )
            logger.info("PaddleOCR 初始化成功")
        except Exception as e:
            logger.error(f"PaddleOCR 初始化失败: {e}")
            raise

    def preprocess_image(self, image_path: str) -> np.ndarray:
        """
        图像预处理

        Args:
            image_path: 图像文件路径

        Returns:
            预处理后的图像
        """
        try:
            # 读取图像
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError("无法读取图像文件")

            # 转为灰度图
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img

            # 增强对比度
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            # 降噪
            denoised = cv2.fastNlMeansDenoising(enhanced)

            # 二值化
            _, binary = cv2.threshold(
                denoised, 0, 255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            return binary

        except Exception as e:
            logger.error(f"图像预处理失败: {e}")
            # 如果预处理失败，返回原始图像
            img = cv2.imread(image_path)
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def extract_table_data(self, image_path: str) -> dict:
        """
        从图像中提取表格数据

        Args:
            image_path: 图像文件路径

        Returns:
            包含表格数据和元信息的字典
        """
        try:
            logger.info(f"开始处理图像: {image_path}")

            # 1. 图像预处理
            processed_img = self.preprocess_image(image_path)

            # 2. 保存预处理后的图像（用于调试）
            debug_path = image_path.replace('.', '_processed.')
            cv2.imwrite(debug_path, processed_img)
            logger.info(f"预处理图像已保存: {debug_path}")

            # 3. OCR 识别
            logger.info("正在执行 OCR 识别...")
            result = self.ocr.ocr(processed_img, cls=True)

            # 4. 解析结果
            logger.info("正在解析识别结果...")
            table_data, table_structure = self._parse_ocr_result(result)

            # 5. 生成 Excel 文件
            excel_path = self._save_to_excel(table_data, image_path)

            return {
                'success': True,
                'table_data': table_data,
                'table_structure': table_structure,
                'excel_path': excel_path,
                'debug_image': debug_path,
                'row_count': len(table_data),
                'col_count': len(table_data[0]) if table_data else 0
            }

        except Exception as e:
            logger.error(f"表格提取失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'table_data': [],
                'table_structure': {}
            }

    def _parse_ocr_result(self, result) -> tuple:
        """
        解析 OCR 结果

        Returns:
            tuple: (表格数据, 表格结构信息)
        """
        if not result or not result[0]:
            return [], {}

        # PaddleOCR 表格识别返回的结构
        ocr_result = result[0]

        # 收集所有文本和位置信息
        cells = []
        for line in ocr_result:
            if len(line) >= 2:
                text = line[1][0]
                points = line[0]

                # 计算边界框
                x_coords = [p[0] for p in points]
                y_coords = [p[1] for p in points]

                cells.append({
                    'text': text.strip(),
                    'bbox': {
                        'x_min': min(x_coords),
                        'x_max': max(x_coords),
                        'y_min': min(y_coords),
                        'y_max': max(y_coords)
                    },
                    'center': {
                        'x': np.mean(x_coords),
                        'y': np.mean(y_coords)
                    }
                })

        # 按行聚类
        cells.sort(key=lambda x: x['center']['y'])

        # 行聚类阈值
        row_threshold = 20
        rows = []
        current_row = []

        for i, cell in enumerate(cells):
            if i == 0:
                current_row.append(cell)
            else:
                if abs(cell['center']['y'] - current_row[0]['center']['y']) < row_threshold:
                    current_row.append(cell)
                else:
                    # 行内按 x 坐标排序
                    current_row.sort(key=lambda x: x['center']['x'])
                    rows.append(current_row)
                    current_row = [cell]

        if current_row:
            current_row.sort(key=lambda x: x['center']['x'])
            rows.append(current_row)

        # 构建表格数据
        table_data = []
        for row in rows:
            row_data = [cell['text'] for cell in row]
            table_data.append(row_data)

        # 表格结构信息
        structure_info = {
            'total_cells': len(cells),
            'total_rows': len(rows),
            'max_columns': max(len(row) for row in rows) if rows else 0,
            'cell_positions': cells
        }

        return table_data, structure_info

    def _save_to_excel(self, table_data: List[List[str]], original_path: str) -> str:
        """
        保存表格数据到 Excel

        Args:
            table_data: 表格数据
            original_path: 原始图像路径

        Returns:
            Excel 文件路径
        """
        try:
            # 创建 DataFrame
            if not table_data:
                raise ValueError("表格数据为空")

            # 确保所有行有相同的列数
            max_cols = max(len(row) for row in table_data)
            for row in table_data:
                row.extend([''] * (max_cols - len(row)))

            df = pd.DataFrame(table_data)

            # 生成 Excel 文件路径
            excel_dir = os.path.join(os.path.dirname(original_path), 'outputs')
            os.makedirs(excel_dir, exist_ok=True)

            excel_filename = os.path.basename(original_path).rsplit('.', 1)[0] + '.xlsx'
            excel_path = os.path.join(excel_dir, excel_filename)

            # 保存为 Excel
            df.to_excel(excel_path, index=False, header=False)
            logger.info(f"Excel 文件已保存: {excel_path}")

            return excel_path

        except Exception as e:
            logger.error(f"保存 Excel 文件失败: {e}")
            raise

    def validate_image(self, image_path: str) -> bool:
        """
        验证图像是否适合表格识别

        Args:
            image_path: 图像文件路径

        Returns:
            是否有效
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                return False

            # 检查图像尺寸
            height, width = img.shape[:2]
            if height < 100 or width < 100:
                return False

            # 检查图像是否太模糊
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

            if laplacian_var < 100:  # 模糊度阈值
                return False

            return True

        except Exception:
            return False


# 全局实例
extractor = TableExtractor(use_gpu=False)
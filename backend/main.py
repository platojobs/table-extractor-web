from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import shutil
import uuid
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from table_extractor import TableExtractor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建应用
app = FastAPI(
    title="表格图片识别转换 API",
    description="将图片中的表格转换为 Excel 文件",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建必要的目录
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 挂载静态文件目录（用于前端访问生成的文件）
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")

# 初始化表格提取器
extractor = TableExtractor(use_gpu=False)


# 数据模型
class ProcessResult(BaseModel):
    success: bool
    message: str
    excel_url: Optional[str] = None
    preview_data: Optional[list] = None
    row_count: Optional[int] = None
    col_count: Optional[int] = None
    error: Optional[str] = None


# 健康检查
@app.get("/")
async def root():
    return {
        "message": "表格图片识别转换 API",
        "status": "运行正常",
        "endpoints": {
            "health": "/health",
            "upload": "/upload (POST)",
            "process": "/process (POST)",
            "list_files": "/files"
        }
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "table-extractor"
    }


# 上传文件
@app.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """
    上传图片文件
    """
    try:
        # 验证文件类型
        allowed_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型。允许的类型: {', '.join(allowed_extensions)}"
            )

        # 生成唯一文件名
        file_id = str(uuid.uuid4())
        filename = f"{file_id}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        # 保存文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info(f"文件上传成功: {filename}")

        # 验证图像
        if not extractor.validate_image(file_path):
            os.remove(file_path)
            raise HTTPException(
                status_code=400,
                detail="图像质量太低或尺寸太小，无法进行表格识别"
            )

        return {
            "success": True,
            "message": "文件上传成功",
            "file_id": file_id,
            "filename": filename,
            "file_path": file_path
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"文件上传失败: {str(e)}"
        )


# 处理图像并提取表格
@app.post("/process")
async def process_image(file_id: str, filename: str):
    """
    处理上传的图片，提取表格并生成 Excel
    """
    try:
        file_path = os.path.join(UPLOAD_DIR, filename)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=404,
                detail="文件不存在"
            )

        logger.info(f"开始处理文件: {filename}")

        # 提取表格数据
        result = extractor.extract_table_data(file_path)

        if not result['success']:
            raise HTTPException(
                status_code=400,
                detail=f"表格识别失败: {result.get('error', '未知错误')}"
            )

        # 生成下载链接
        excel_filename = os.path.basename(result['excel_path'])
        excel_url = f"/outputs/{excel_filename}"

        # 准备预览数据（前5行）
        preview_data = result['table_data'][:5] if result['table_data'] else []

        # 清理临时文件（可选）
        # os.remove(file_path)
        # if 'debug_image' in result and os.path.exists(result['debug_image']):
        #     os.remove(result['debug_image'])

        return ProcessResult(
            success=True,
            message="表格识别成功",
            excel_url=excel_url,
            preview_data=preview_data,
            row_count=result['row_count'],
            col_count=result['col_count']
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"处理失败: {str(e)}"
        )


# 批量处理
@app.post("/batch-process")
async def batch_process(files: list[UploadFile] = File(...)):
    """
    批量处理多个图片文件
    """
    results = []

    for file in files:
        try:
            # 上传文件
            upload_result = await upload_image(file)

            # 处理文件
            process_result = await process_image(
                upload_result['file_id'],
                upload_result['filename']
            )

            results.append({
                "filename": file.filename,
                "success": True,
                "excel_url": process_result.excel_url,
                "row_count": process_result.row_count,
                "col_count": process_result.col_count
            })

        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e)
            })

    return {
        "total": len(files),
        "successful": len([r for r in results if r['success']]),
        "failed": len([r for r in results if not r['success']]),
        "results": results
    }


# 列出已生成的文件
@app.get("/files")
async def list_files():
    """
    列出所有已生成的 Excel 文件
    """
    try:
        files = []
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith('.xlsx'):
                file_path = os.path.join(OUTPUT_DIR, filename)
                stat = os.stat(file_path)
                files.append({
                    "filename": filename,
                    "url": f"/outputs/{filename}",
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
                })

        return {
            "success": True,
            "count": len(files),
            "files": sorted(files, key=lambda x: x['created'], reverse=True)
        }

    except Exception as e:
        logger.error(f"列出文件失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"列出文件失败: {str(e)}"
        )


# 下载文件
@app.get("/download/{filename}")
async def download_file(filename: str):
    """
    下载 Excel 文件
    """
    file_path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="文件不存在"
        )

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# 清理旧文件（可选，可以设置定时任务）
@app.post("/cleanup")
async def cleanup_files(days_old: int = 7):
    """
    清理指定天数前的文件
    """
    try:
        deleted_count = 0
        now = datetime.now().timestamp()

        # 清理上传目录
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            stat = os.stat(file_path)
            if (now - stat.st_mtime) > (days_old * 86400):
                os.remove(file_path)
                deleted_count += 1

        # 清理输出目录
        for filename in os.listdir(OUTPUT_DIR):
            file_path = os.path.join(OUTPUT_DIR, filename)
            stat = os.stat(file_path)
            if (now - stat.st_mtime) > (days_old * 86400):
                os.remove(file_path)
                deleted_count += 1

        return {
            "success": True,
            "message": f"清理了 {deleted_count} 个旧文件",
            "deleted_count": deleted_count
        }

    except Exception as e:
        logger.error(f"清理文件失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"清理文件失败: {str(e)}"
        )


# 启动脚本
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
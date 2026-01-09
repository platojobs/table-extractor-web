// API 基础 URL
const API_BASE_URL = 'http://localhost:8000';

// DOM 元素
const fileInput = document.getElementById('fileInput');
const uploadArea = document.getElementById('uploadArea');
const fileListContent = document.getElementById('fileListContent');
const processBtn = document.getElementById('processBtn');
const clearBtn = document.getElementById('clearBtn');
const imagePreview = document.getElementById('imagePreview');
const tablePreview = document.getElementById('tablePreview');
const resultSection = document.getElementById('resultSection');
const loadingOverlay = document.getElementById('loadingOverlay');
const loadingMessage = document.getElementById('loadingMessage');
const progressFill = document.getElementById('progressFill');
const downloadLink = document.getElementById('downloadLink');
const processAnother = document.getElementById('processAnother');

// 状态管理
const state = {
    files: [],
    uploadedFileIds: {},
    processing: false
};

// 初始化
function init() {
    setupEventListeners();
    checkServerStatus();
}

// 设置事件监听器
function setupEventListeners() {
    // 文件输入变化
    fileInput.addEventListener('change', handleFileSelect);

    // 拖放事件
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);

    // 点击上传区域
    uploadArea.addEventListener('click', () => fileInput.click());

    // 处理按钮
    processBtn.addEventListener('click', handleProcess);

    // 清空按钮
    clearBtn.addEventListener('click', clearFileList);

    // 处理新文件按钮
    processAnother.addEventListener('click', handleProcessAnother);

    // 点击外部关闭预览
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.file-item') && !e.target.closest('.preview-content')) {
            // 可以添加其他关闭逻辑
        }
    });
}

// 检查服务器状态
async function checkServerStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
        if (response.ok) {
            console.log('服务器连接正常');
        } else {
            showToast('服务器连接失败，请检查后端服务是否启动', 'error');
        }
    } catch (error) {
        console.error('服务器连接失败:', error);
        showToast('无法连接到服务器，请确保后端服务正在运行', 'error');
    }
}

// 处理文件选择
function handleFileSelect(event) {
    const files = Array.from(event.target.files);
    addFiles(files);
    fileInput.value = ''; // 重置 input
}

// 处理拖放
function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    uploadArea.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    uploadArea.classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    uploadArea.classList.remove('dragover');

    const files = Array.from(e.dataTransfer.files);
    addFiles(files);
}

// 添加文件到列表
function addFiles(files) {
    const validFiles = files.filter(file => {
        const validTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/bmp', 'image/tiff'];
        const maxSize = 10 * 1024 * 1024; // 10MB

        if (!validTypes.includes(file.type)) {
            showToast(`文件 ${file.name} 不是支持的图片格式`, 'error');
            return false;
        }

        if (file.size > maxSize) {
            showToast(`文件 ${file.name} 太大，最大支持 10MB`, 'error');
            return false;
        }

        return true;
    });

    validFiles.forEach(file => {
        // 避免重复文件
        const existingFile = state.files.find(f => f.name === file.name && f.size === file.size);
        if (!existingFile) {
            state.files.push(file);
        }
    });

    updateFileList();
    updateProcessButton();
    previewFirstImage();
}

// 更新文件列表显示
function updateFileList() {
    if (state.files.length === 0) {
        fileListContent.innerHTML = '<p class="empty-message">暂无文件</p>';
        return;
    }

    fileListContent.innerHTML = state.files.map((file, index) => `
        <div class="file-item" data-index="${index}">
            <div class="file-info">
                <i class="fas fa-file-image file-icon"></i>
                <div>
                    <div class="file-name">${file.name}</div>
                    <div class="file-size">${formatFileSize(file.size)}</div>
                </div>
            </div>
            <button class="remove-file" onclick="removeFile(${index})" title="移除文件">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');
}

// 移除文件
function removeFile(index) {
    state.files.splice(index, 1);
    delete state.uploadedFileIds[index];
    updateFileList();
    updateProcessButton();
    previewFirstImage();
}

// 清空文件列表
function clearFileList() {
    state.files = [];
    state.uploadedFileIds = {};
    updateFileList();
    updateProcessButton();
    clearPreviews();
    hideResultSection();
}

// 更新处理按钮状态
function updateProcessButton() {
    processBtn.disabled = state.files.length === 0 || state.processing;
}

// 预览第一张图片
function previewFirstImage() {
    if (state.files.length > 0) {
        const file = state.files[0];
        const reader = new FileReader();

        reader.onload = (e) => {
            imagePreview.innerHTML = `
                <img src="${e.target.result}" alt="预览">
                <div class="image-info">
                    <small>${file.name} (${formatFileSize(file.size)})</small>
                </div>
            `;
        };

        reader.readAsDataURL(file);
    } else {
        imagePreview.innerHTML = `
            <div class="preview-placeholder">
                <i class="fas fa-image"></i>
                <p>选择图片后显示预览</p>
            </div>
        `;
    }
}

// 清除预览
function clearPreviews() {
    imagePreview.innerHTML = `
        <div class="preview-placeholder">
            <i class="fas fa-image"></i>
            <p>选择图片后显示预览</p>
        </div>
    `;

    tablePreview.innerHTML = `
        <div class="preview-placeholder">
            <i class="fas fa-table"></i>
            <p>识别结果将显示在这里</p>
        </div>
    `;
}

// 处理文件
async function handleProcess() {
    if (state.files.length === 0 || state.processing) return;

    state.processing = true;
    updateProcessButton();
    showLoading('正在上传文件...');

    try {
        // 上传文件并获取 file_id
        const uploadResults = [];

        for (let i = 0; i < state.files.length; i++) {
            progressFill.style.width = `${(i / state.files.length) * 100}%`;
            loadingMessage.textContent = `正在上传文件 ${i + 1}/${state.files.length}...`;

            const formData = new FormData();
            formData.append('file', state.files[i]);

            const response = await fetch(`${API_BASE_URL}/upload`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`上传失败: ${response.statusText}`);
            }

            const result = await response.json();
            uploadResults.push({
                index: i,
                fileId: result.file_id,
                filename: result.filename
            });
        }

        // 处理每个文件
        const processResults = [];

        for (let i = 0; i < uploadResults.length; i++) {
            const { index, fileId, filename } = uploadResults[i];

            progressFill.style.width = `${((i + 1) / uploadResults.length) * 100}%`;
            loadingMessage.textContent = `正在处理文件 ${i + 1}/${uploadResults.length}...`;

            const response = await fetch(`${API_BASE_URL}/process?file_id=${fileId}&filename=${filename}`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error(`处理失败: ${response.statusText}`);
            }

            const result = await response.json();
            processResults.push({
                index,
                result
            });
        }

        // 显示第一个文件的结果
        if (processResults.length > 0) {
            const firstResult = processResults[0].result;
            displayResult(firstResult);
        }

        showToast(`成功处理 ${processResults.length} 个文件`, 'success');

    } catch (error) {
        console.error('处理失败:', error);
        showToast(`处理失败: ${error.message}`, 'error');
    } finally {
        state.processing = false;
        updateProcessButton();
        hideLoading();
    }
}

// 显示处理结果
function displayResult(result) {
    // 更新表格预览
    if (result.preview_data && result.preview_data.length > 0) {
        let tableHTML = '<table>';

        // 如果有表头，可以单独处理
        const hasHeader = result.preview_data.length > 1;

        result.preview_data.forEach((row, rowIndex) => {
            tableHTML += '<tr>';
            row.forEach(cell => {
                const tag = hasHeader && rowIndex === 0 ? 'th' : 'td';
                tableHTML += `<${tag}>${cell || ''}</${tag}>`;
            });
            tableHTML += '</tr>';
        });

        tableHTML += '</table>';
        tablePreview.innerHTML = tableHTML;
    }

    // 显示结果区域
    document.getElementById('rowCount').textContent = result.row_count || 0;
    document.getElementById('colCount').textContent = result.col_count || 0;
    document.getElementById('cellCount').textContent = (result.row_count || 0) * (result.col_count || 0);

    // 设置下载链接
    if (result.excel_url) {
        downloadLink.href = `${API_BASE_URL}${result.excel_url}`;
        downloadLink.download = 'table.xlsx';
    }

    resultSection.style.display = 'block';

    // 滚动到结果区域
    resultSection.scrollIntoView({ behavior: 'smooth' });
}

// 隐藏结果区域
function hideResultSection() {
    resultSection.style.display = 'none';
}

// 处理新文件
function handleProcessAnother() {
    hideResultSection();
    clearFileList();
}

// 显示加载动画
function showLoading(message) {
    loadingMessage.textContent = message || '正在处理中...';
    progressFill.style.width = '0%';
    loadingOverlay.style.display = 'flex';
}

// 隐藏加载动画
function hideLoading() {
    loadingOverlay.style.display = 'none';
}

// 显示提示消息
function showToast(message, type = 'info') {
    const backgroundColor = type === 'success' ? '#48bb78' :
                           type === 'error' ? '#f56565' : '#4299e1';

    Toastify({
        text: message,
        duration: 3000,
        gravity: "top",
        position: "center",
        backgroundColor: backgroundColor,
        stopOnFocus: true
    }).showToast();
}

// 工具函数
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);

// 全局导出函数
window.removeFile = removeFile;
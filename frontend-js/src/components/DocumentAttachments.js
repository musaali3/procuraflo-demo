import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import client from '../api/client';
import useAutoRefresh from '../hooks/useAutoRefresh';
export default function DocumentAttachments({ type, documentId, onUploaded }) {
    const [files, setFiles] = useState([]);
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState('');
    const load = () => client.get(`/attachments/${type}/${documentId}`).then((r) => setFiles(r.data)).catch(() => setError('Unable to load attachments'));
    useAutoRefresh(load, { predicate: ({ url }) => String(url || '') === `/attachments/${type}/${documentId}` });
    useEffect(() => { load(); }, [type, documentId]);
    async function upload() {
        if (!file || uploading)
            return;
        setUploading(true);setError('');
        const body = new FormData();
        body.append('file', file);
        try {
            const response = await client.post(`/attachments/${type}/${documentId}`, body);
            setFile(null);
            setError('');
            await load();
            onUploaded?.(response.data);
        }
        catch (e) {
            setError(e?.response?.data?.error || e?.response?.data?.detail || (e?.response?.status >= 500 ? 'The server could not save the attachment. Please retry; if it continues, contact your administrator.' : 'Upload failed. Check your connection and try again.'));
        } finally {setUploading(false);}
    }
    async function openFile(f) { try {
        const response = await client.get(`/attachments/file/${f.id}`, { responseType: 'blob' });
        const url = URL.createObjectURL(response.data);
        window.open(url, '_blank', 'noopener,noreferrer');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    catch {
        setError('You are not authorized to open this document');
    } }
    const quotation = type === 'QUOTATION';
    return _jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("div", { className: "font-medium text-slate-700 mb-2", children: quotation ? "Permanent Supplier Quotation Evidence" : "Supporting Documents" }), _jsx("div", { className: "space-y-1 mb-2", children: files.length ? files.map((f) => _jsxs("button", { type: "button", className: "block text-left text-brand-600 hover:underline", onClick: () => openFile(f), children: [f.original_name, " ", _jsxs("span", { className: "text-xs text-slate-400", children: ["(", f.uploaded_by_name, ", ", f.uploaded_at, ")"] })] }, f.id)) : _jsx("div", { className: "text-xs text-slate-400", children: "No documents uploaded." }) }), _jsx("label", { className: "block text-sm font-medium text-slate-700 mb-1", children: quotation ? "Upload original PDF, image, or Excel quotation" : "Select PDF or image to upload" }), _jsxs("div", { className: "flex gap-2", children: [_jsx("input", { className: "input", "aria-label": "Supporting document file", "data-field": "file", type: "file", accept: quotation ? "application/pdf,image/jpeg,image/png,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/pdf,image/jpeg,image/png", onChange: (e) => setFile(e.target.files?.[0] || null) }), _jsx("button", { className: "btn-secondary", disabled: !file || uploading, onClick: upload, children: uploading ? "Uploading..." : "Upload" })] }), quotation && _jsx("div", { className: "mt-2 text-xs text-slate-500", children: "Uploaded evidence is retained permanently. Use a controlled quotation revision instead of replacing the original." }), error && _jsx("div", {"data-error-message": true, role: "alert",  className: "text-xs text-rose-600 mt-1", children: error })] });
}

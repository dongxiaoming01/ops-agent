from flask import jsonify, request, abort, send_from_directory
from flask.views import MethodView

from tools.pdf_report import verify_download_token, REPORT_DIR


class DownloadAPI(MethodView):
    @staticmethod
    def get():
        expires = request.args.get("expires", "")
        token = request.args.get("token", "")
        filename = request.args.get("filename", "")
        if not verify_download_token(filename, expires, token):
            abort(403)

        report_path = REPORT_DIR / filename
        if not report_path.is_file() or report_path.parent != REPORT_DIR:
            abort(404)

        return send_from_directory(
            str(REPORT_DIR),
            filename,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
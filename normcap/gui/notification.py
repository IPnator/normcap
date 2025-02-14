import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Optional, Union

from PySide6 import QtCore, QtGui, QtWidgets

from normcap.gui import system_info
from normcap.gui.localization import _, translate
from normcap.gui.models import Capture, TextDetector, TextType

logger = logging.getLogger(__name__)


def _compose_title(capture: Capture) -> str:
    if not capture.text:
        return ""

    if capture.text_type == TextType.PARAGRAPH:
        count = capture.text.count(os.linesep * 2) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 paragraph captured", "{count} paragraphs captured", count
        ).format(count=count)
    elif capture.text_type == TextType.MAIL:
        count = capture.text.count("@")
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 email captured", "{count} emails captured", count
        ).format(count=count)
    elif capture.text_type == TextType.SINGLE_LINE:
        count = capture.text.count(" ") + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 word captured", "{count} words captured", count
        ).format(count=count)
    elif capture.text_type == TextType.MULTI_LINE:
        count = capture.text.count(os.linesep) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 line captured", "{count} lines captured", count
        ).format(count=count)
    elif capture.text_type == TextType.URL:
        count = capture.text.count(os.linesep) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 URL captured", "{count} URLs captured", count
        ).format(count=count)
    elif capture.detector == TextDetector.QR:
        count = capture.text.count(os.linesep) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 QR code detected", "{count} QR codes detected", count
        ).format(count=count)
    elif capture.detector == TextDetector.BARCODE:
        count = capture.text.count(os.linesep) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 barcode detected", "{count} barcodes detected", count
        ).format(count=count)
    elif capture.detector == TextDetector.QR_AND_BARCODE:
        count = capture.text.count(os.linesep) + 1
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 code detected", "{count} codes detected", count
        ).format(count=count)
    else:
        count = len(capture.text)
        # Count linesep only as single char:
        count -= (len(os.linesep) - 1) * capture.text.count(os.linesep)
        # L10N: Notification title.
        # Do NOT translate the variables in curly brackets "{some_variable}"!
        title = translate.ngettext(
            "1 character captured", "{count} characters captured", count
        ).format(count=count)
    return title


def _compose_text(capture: Capture) -> str:
    if not capture.text:
        return ""

    text = capture.text.strip().replace(os.linesep, " ")
    shortened = textwrap.shorten(text, width=45, placeholder=" […]")
    if shortened == " […]":
        # We have one long word which shorten() can not handle
        shortened = text[:44] + "…"

    return shortened


def _compose_notification(capture: Capture) -> tuple[str, str]:
    """Extract message text out of captures object and include icon."""
    # Compose message text
    if capture.text and capture.text.strip():
        title = _compose_title(capture=capture)
        text = _compose_text(capture=capture)
    else:
        # L10N: Notification title
        title = _("Nothing captured!")
        # L10N: Notification text
        text = _("Please try again.")

    return title, text


class Communicate(QtCore.QObject):
    """Notifier's communication bus."""

    send_notification = QtCore.Signal(Capture)
    on_notification_sent = QtCore.Signal()


class Notifier(QtCore.QObject):
    """Send notifications."""

    def __init__(self, parent: Optional[QtCore.QObject]) -> None:
        super().__init__(parent=parent)
        self.com = Communicate(parent=self)
        self.com.send_notification.connect(self._send_notification)

    @QtCore.Slot(Capture)  # type: ignore  # pyside typhint bug?
    def _send_notification(self, capture: Capture) -> None:
        """Show tray icon then send notification."""
        title, message = _compose_notification(capture)
        if sys.platform == "linux" and shutil.which("notify-send"):
            self._send_via_libnotify(title=title, message=message)
        else:
            self._send_via_qt_tray(
                title=title,
                message=message,
                text=capture.text,
                text_type=capture.text_type,
            )
        self.com.on_notification_sent.emit()

    @staticmethod
    def _send_via_libnotify(title: str, message: str) -> None:
        """Send via notify-send.

        Seems to work more reliable on Linux + Gnome, but requires libnotify.
        Running in detached mode to avoid freezing KDE bar in some distributions.

        A drawback is, that it's difficult to receive clicks on the notification
        like it's done with the Qt method. `notify-send` _is_ able to support this,
        but it would require leaving the subprocess running and monitoring its output,
        which doesn't feel very solid.

        ONHOLD: Switch from notify-send to org.freedesktop.Notifications.
        A cleaner way would be to use DBUS org.freedesktop.Notifications instead of
        notify-send, but this seems to be quite difficult to implement with QtDbus,
        where the types seem not to be correctly casted to DBUS-Types. A future PySide
        version might improve the situation.
        """
        logger.debug("Send notification via notify-send")
        icon_path = system_info.get_resources_path() / "icons" / "notification.png"

        # Escape chars interpreted by notify-send
        message = message.replace("\\", "\\\\")
        message = message.replace("-", "\\-")

        cmds = [
            "notify-send",
            f"--icon={icon_path.resolve()}",
            "--app-name=NormCap",
            f"{title}",
            f"{message}",
        ]

        # Left detached on purpose!
        subprocess.Popen(cmds, start_new_session=True)  # noqa: S603

    def _send_via_qt_tray(
        self,
        title: str,
        message: str,
        text: Optional[str],
        text_type: Optional[TextType],
    ) -> None:
        """Send via QSystemTrayIcon.

        Used for:
            - Windows
            - macOS
            - Linux (Fallback in case no notify-send)

        On Linux, this method has draw backs (probably Qt Bugs):
            - The custom icon is ignored. Instead the default icon
              `QtWidgets.QSystemTrayIcon.MessageIcon.Information` is shown.
            - Notifications clicks are not received. It _does_ work, if
              `QtWidgets.QSystemTrayIcon.MessageIcon.Critical` is used as icon.
        """
        logger.debug("Send notification via QT")

        parent = self.parent()

        if not isinstance(parent, QtWidgets.QSystemTrayIcon):
            raise TypeError("Parent is expected to be of type QSystemTrayIcon.")

        # Because clicks on different notifications can not be distinguished in Qt,
        # only the last notification is associated with an action/signal. All previous
        # get removed.
        if parent.isSignalConnected(
            QtCore.QMetaMethod.fromSignal(parent.messageClicked)
        ):
            parent.messageClicked.disconnect()

        # It only makes sense to act on notification clicks, if we have a result.
        if text and len(text.strip()) >= 1:
            parent.messageClicked.connect(
                lambda: self._open_ocr_result(text=text, text_type=text_type)
            )

        parent.show()
        parent.showMessage(title, message, QtGui.QIcon(":notification"))

    @staticmethod
    def _open_ocr_result(text: str, text_type: Union[TextType, None]) -> None:
        logger.debug("Notification clicked.")

        urls = []
        if text_type == TextType.URL:
            urls = text.split()
        elif text_type == TextType.MAIL:
            urls = [f"mailto:{text.replace(',', ';').replace(' ', '')}"]
        else:
            temp_file = Path(tempfile.gettempdir()) / "normcap_temporary_result.txt"
            temp_file.write_text(text)
            urls = [temp_file.as_uri()]

        for url in urls:
            logger.debug("Opening URI %s...", url)
            result = QtGui.QDesktopServices.openUrl(
                QtCore.QUrl(url, QtCore.QUrl.ParsingMode.TolerantMode)
            )
            logger.debug("Opened URI with result=%s", result)

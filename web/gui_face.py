#!/usr/bin/env python3
"""
Lightweight PyQt5 GUI face for Raspberry Pi display.
Shows animated eyes and mouth, responds to companion state changes.
Lightweight enough to run on Pi 5 without heavy browser overhead.
"""

import sys
import time
import threading
import logging
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                              QHBoxLayout, QPushButton, QSlider, QComboBox,
                              QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QPixmap,
                          QMovie, QConicalGradient, QRadialGradient)

logger = logging.getLogger(__name__)


class AnimatedEye(QWidget):
    """Single animated eye widget."""
    
    def __init__(self, size=80, parent=None):
        super().__init__(parent)
        self.size = size
        self.pupil_x = 0
        self.pupil_y = 0
        self.blinking = False
        self.blink_progress = 0
        self.state = "idle"  # idle, listening, thinking, speaking, happy
        self.setFixedSize(size, size)
        self.setMouseTracking(True)
        
    def set_state(self, state):
        self.state = state
        self.update()
        
    def set_blink(self, value):
        self.blink_progress = value
        self.update()
        
    def mouseMoveEvent(self, event):
        """Track mouse position for pupil following."""
        pos = event.pos()
        cx, cy = self.width() / 2, self.height() / 2
        dx = (pos.x() - cx) / (self.width() / 2)
        dy = (pos.y() - cy) / (self.height() / 2)
        self.pupil_x = dx * 15
        self.pupil_y = dy * 15
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        cx, cy = self.width() / 2, self.height() / 2
        r = self.size / 2
        
        # Calculate blink scaleY
        if self.blink_progress > 0:
            scale_y = max(0.1, 1.0 - self.blink_progress)
        else:
            scale_y = 1.0
        
        # Draw eye white
        painter.save()
        painter.translate(cx, cy)
        painter.scale(1, scale_y)
        
        eye_color = QColor(255, 255, 255)
        eye_pen = QPen(QColor(100, 100, 120), 3)
        painter.setPen(eye_pen)
        painter.setBrush(QBrush(eye_color))
        painter.drawEllipse(QRectF(-r, -r, r*2, r*2))
        
        # Draw colored iris based on state
        if self.state == "idle":
            iris_color = QColor(100, 200, 255)  # Calm blue
        elif self.state == "listening":
            iris_color = QColor(100, 255, 150)  # Green
        elif self.state == "thinking":
            iris_color = QColor(255, 200, 100)  # Amber
        elif self.state == "speaking":
            iris_color = QColor(255, 150, 100)  # Orange
        elif self.state == "happy":
            iris_color = QColor(255, 220, 50)   # Yellow
        elif self.state == "listening":
            iris_color = QColor(150, 100, 255)  # Purple
        else:
            iris_color = QColor(100, 200, 255)
        
        iris_r = r * 0.5
        painter.setBrush(QBrush(iris_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(-iris_r, -iris_r, iris_r*2, iris_r*2))
        
        # Draw pupil
        pupil_r = iris_r * 0.5
        painter.setBrush(QBrush(QColor(20, 20, 30)))
        painter.drawEllipse(
            QRectF(
                self.pupil_x - pupil_r,
                self.pupil_y - pupil_r,
                pupil_r*2, pupil_r*2
            )
        )
        
        # Draw highlight
        highlight_r = pupil_r * 0.4
        painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
        painter.drawEllipse(
            QRectF(
                self.pupil_x - highlight_r + 3,
                self.pupil_y - highlight_r - 3,
                highlight_r*2, highlight_r*2
            )
        )
        
        painter.restore()
        painter.end()


class Mouth(QWidget):
    """Animated mouth widget."""
    
    def __init__(self, width=120, parent=None):
        super().__init__(parent)
        self.width_val = width
        self.height = 30
        self.state = "idle"
        self.mouth_open = 0.0
        self.setFixedSize(width, height)
        
    def set_state(self, state):
        self.state = state
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        cx, cy = self.width_val / 2, self.height / 2
        
        # Clear background
        painter.fillRect(0, 0, self.width_val, self.height, QColor(15, 15, 25))
        
        # Draw mouth based on state
        mouth_color = QColor(100, 200, 255)
        
        if self.state == "idle":
            # Smile
            painter.setPen(QPen(mouth_color, 3))
            painter.setBrush(Qt.NoBrush)
            path = painter.path()
            path.moveTo(20, cy)
            path.quadTo(cx, cy + 15, self.width_val - 20, cy)
            painter.drawPath(path)
            
        elif self.state == "listening":
            # Small circle (listening)
            painter.setPen(QPen(mouth_color, 2))
            painter.setBrush(mouth_color)
            painter.drawEllipse(cx - 10, cy - 10, 20, 20)
            
        elif self.state == "thinking":
            # Wavy line (thinking)
            painter.setPen(QPen(mouth_color, 3))
            painter.setBrush(Qt.NoBrush)
            path = painter.path()
            path.moveTo(20, cy)
            path.quadTo(cx - 20, cy - 10, cx, cy + 5)
            path.quadTo(cx + 20, cy + 15, self.width_val - 20, cy)
            painter.drawPath(path)
            
        elif self.state == "speaking":
            # Open mouth (animated)
            open_amount = 0.5 + 0.5 * (0.5 + 0.5 * __import__('math').sin(time.time() * 8))
            mouth_h = 10 + open_amount * 20
            painter.setPen(QPen(mouth_color, 2))
            painter.setBrush(mouth_color)
            painter.drawEllipse(cx - 25, cy - mouth_h/2, 50, mouth_h)
            
        elif self.state == "happy":
            # Big smile
            painter.setPen(QPen(mouth_color, 4))
            painter.setBrush(Qt.NoBrush)
            path = painter.path()
            path.moveTo(10, cy - 5)
            path.quadTo(cx, cy + 25, self.width_val - 10, cy - 5)
            painter.drawPath(path)
            
        elif self.state == "listening":
            # O shape (listening)
            painter.setPen(QPen(mouth_color, 2))
            painter.setBrush(QColor(100, 200, 255, 50))
            painter.drawEllipse(cx - 15, cy - 15, 30, 30)
        
        painter.end()


class FaceWidget(QWidget):
    """Main face widget with eyes and mouth."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._start_blink)
        self.blink_timer.start(3000 + __import__('random').randint(0, 4000))
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        
        # Face container
        face_container = QFrame()
        face_container.setStyleSheet("""
            QFrame {
                background-color: rgb(15, 15, 25);
                border-radius: 40px;
            }
        """)
        
        face_layout = QVBoxLayout(face_container)
        face_layout.setContentsMargins(40, 40, 40, 40)
        face_layout.setSpacing(40)
        
        # Eyes row
        eyes_layout = QHBoxLayout()
        eyes_layout.setSpacing(80)
        
        self.left_eye = AnimatedEye(80)
        self.right_eye = AnimatedEye(80)
        eyes_layout.addWidget(self.left_eye)
        eyes_layout.addWidget(self.right_eye)
        
        # Mouth
        self.mouth = Mouth(120)
        
        face_layout.addLayout(eyes_layout)
        face_layout.addWidget(self.mouth, alignment=Qt.AlignCenter)
        
        layout.addWidget(face_container, 1)
        
        # State label
        self.state_label = QLabel("Idle")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("""
            QLabel {
                color: rgb(150, 200, 255);
                font-size: 18px;
                font-family: monospace;
                padding: 10px;
            }
        """)
        layout.addWidget(self.state_label)
        
        self.set_background()
        
    def set_background(self):
        """Set dark background."""
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(10, 10, 15))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        
    def set_state(self, state):
        """Update face state."""
        self.state = state
        self.left_eye.set_state(state)
        self.right_eye.set_state(state)
        self.mouth.set_state(state)
        
        labels = {
            "idle": "👁️ Idle",
            "listening": "👂 Listening...",
            "thinking": "🤔 Thinking...",
            "speaking": "🗣️ Speaking...",
            "happy": "😊 Happy",
            "error": "❌ Error",
        }
        self.state_label.setText(labels.get(state, f"💬 {state.title()}"))
        self.update()
        
    def _start_blink(self):
        """Start blink animation."""
        self.left_eye.set_blink(1.0)
        self.right_eye.set_blink(1.0)
        QTimer.singleShot(150, self._end_blink)
        
    def _end_blink(self):
        """End blink animation."""
        self.left_eye.set_blink(0.0)
        self.right_eye.set_blink(0.0)
        self.blink_timer.start(3000 + __import__('random').randint(0, 4000))


class FaceApp(QWidget):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Red Queen AI Companion")
        self.state = "idle"
        
        # Setup face widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.face = FaceWidget()
        layout.addWidget(self.face)
        
        # Status bar
        self.status = QLabel("Connected to Red Queen")
        self.status.setStyleSheet("color: rgb(100, 200, 100); font-size: 14px;")
        layout.addWidget(self.status)
        
        # Set geometry
        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width() * 0.4, screen.height() * 0.5)
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )
        
    def set_state(self, state):
        """Update face state."""
        self.state = state
        self.face.set_state(state)
        
        if state == "idle":
            self.status.setText("Connected to Red Queen")
            self.status.setStyleSheet("color: rgb(100, 200, 100);")
        elif state == "listening":
            self.status.setText("Listening...")
            self.status.setStyleSheet("color: rgb(100, 200, 255);")
        elif state == "thinking":
            self.status.setText("Thinking...")
            self.status.setStyleSheet("color: rgb(255, 200, 100);")
        elif state == "speaking":
            self.status.setText("Speaking...")
            self.status.setStyleSheet("color: rgb(255, 150, 100);")
        elif state == "happy":
            self.status.setText("Happy!")
            self.status.setStyleSheet("color: rgb(255, 220, 50);")
        elif state == "error":
            self.status.setText("Error!")
            self.status.setStyleSheet("color: rgb(255, 100, 100);")


def run_face_gui():
    """Run the face GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Red Queen Companion")
    
    face = FaceApp()
    face.show()
    
    logger.info("Face GUI started")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_face_gui()

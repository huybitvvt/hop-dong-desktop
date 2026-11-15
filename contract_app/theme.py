STYLE = """
* { font-family: 'Noto Sans'; font-size: 13px; color: #17243B; }
QMainWindow, QDialog { background: #F4F7FB; }
QScrollArea, QScrollArea > QWidget, QWidget#FormContent { background: #F4F7FB; color: #17243B; }
QWidget#Sidebar { background: #10233F; }
QLabel#Brand { color: white; font-size: 23px; font-weight: 700; }
QLabel#BrandSub { color: #BAC8DC; font-size: 12px; }
QLabel#NavCaption { color: #91A6C2; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QPushButton#NavButton { color: #CFDAE8; background: transparent; border: 0; border-radius: 8px; text-align: left; padding: 13px 15px; font-weight: 600; }
QPushButton#NavButton:hover { background: #1D3556; color: white; }
QPushButton#NavButton:checked { background: #25486F; color: white; }
QLabel#Title { font-size: 26px; font-weight: 700; color: #10233F; }
QLabel#Subtitle { color: #56667D; font-size: 13px; }
QLabel#SectionTitle { font-size: 16px; font-weight: 700; }
QLabel#Muted { color: #586A82; }
QLabel#Badge { background: #E7EFFB; color: #1D4ED8; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
QLabel#Warning { background: #FFF6DB; color: #755014; padding: 10px 13px; border: 1px solid #E9D8A6; border-radius: 7px; }
QFrame#Card { background: white; border: 1px solid #DAE2EE; border-radius: 12px; }
QPushButton { background: white; border: 1px solid #C9D5E5; border-radius: 7px; padding: 9px 14px; font-weight: 600; min-height: 20px; }
QPushButton:hover { background: #EDF3FC; border-color: #8EA9D2; }
QPushButton:pressed { background: #E0EAF8; }
QPushButton#CompactButton { min-height: 20px; padding: 4px 9px; }
QPushButton:disabled { color: #738198; background: #EDF0F5; border-color: #DFE5ED; }
QPushButton#Primary { background: #1D4ED8; color: white; border-color: #1D4ED8; }
QPushButton#Primary:hover { background: #1E40AF; }
QPushButton#Primary:disabled { background: #8AA3D7; border-color: #8AA3D7; color: white; }
QPushButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QTableWidget:focus, QListWidget:focus { border: 2px solid #2563EB; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #C9D5E5; border-radius: 7px; padding: 9px; selection-background-color: #DBEAFE; selection-color: #10233F; }
QComboBox { min-height: 22px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #DBEAFE; color: #17243B; padding: 6px; }
QTextBrowser { background: transparent; border: 0; padding: 4px; }
QTextBrowser#TemplatePreview { background: white; border: 1px solid #C9D5E5; border-radius: 7px; padding: 7px; }
QTableWidget, QListWidget { background: white; border: 1px solid #DAE2EE; border-radius: 8px; gridline-color: #E5EBF4; selection-background-color: #DBEAFE; selection-color: #10233F; alternate-background-color: #F8FAFD; }
QHeaderView::section { background: #EDF2F9; color: #43566E; border: 0; border-bottom: 1px solid #DAE2EE; padding: 11px; font-weight: 600; }
QTableCornerButton::section { background: #EDF2F9; border: 0; }
QTableWidget::item { padding: 8px; }
QScrollArea { border: 0; background: transparent; }
QProgressBar { border: 0; background: #E5ECF6; border-radius: 3px; max-height: 4px; }
QProgressBar::chunk { background: #2563EB; }
QCheckBox { spacing: 8px; }
QToolTip { color: #17243B; background: white; border: 1px solid #C9D5E5; padding: 6px; }
QStatusBar { background: #EAF0F8; color: #43566E; border-top: 1px solid #DAE2EE; }
"""

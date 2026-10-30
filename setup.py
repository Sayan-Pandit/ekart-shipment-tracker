from setuptools import setup, find_packages

setup(
    name="ekart-tracker",
    version="1.0.0",
    description="Ekart Logistics Shipment Tracker with Server Daemon, Dual Notifications (Email & Webhook), and Terminal Interface",
    author="Antigravity",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
        "Flask>=2.3.0",
        "flask-cors>=4.0.0",
        "rich>=13.0.0",
        "click>=8.0.0",
        "python-dotenv>=1.0.0",
        "colorama>=0.4.6"
    ],
    entry_points={
        "console_scripts": [
            "ekart-tracker=ekart_tracker.cli:cli",
        ],
    },
    python_requires=">=3.8",
)


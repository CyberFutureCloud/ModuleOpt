import threading
import queue
import time
import random
import docker
import psutil
import requests
import sqlite3
from prometheus_client import start_http_server, Gauge

class TaskManager:
    def __init__(self, max_threads=5, api_rate_limit=1.5, max_containers=3, webhook_url=None, db_path='task_manager.db'):
        """
        :param max_threads: Maksymalna liczba wątków działających jednocześnie.
        :param api_rate_limit: Minimalny czas (sekundy) między requestami do API Discorda.
        :param max_containers: Maksymalna liczba uruchomionych kontenerów dla botów.
        :param webhook_url: URL do wysyłania powiadomień webhookiem.
        :param db_path: Ścieżka do bazy danych SQLite do przechowywania logów.
        """
        self.task_queue = queue.PriorityQueue()
        self.max_threads = max_threads
        self.api_rate_limit = api_rate_limit
        self.max_containers = max_containers
        self.webhook_url = webhook_url
        self.db_path = db_path
        self.threads = []
        self.lock = threading.Lock()
        self.last_request_time = time.time()
        self.docker_client = docker.from_env()
        self.containers = {}
        self.load_history = []

        # Prometheus metrics
        self.cpu_usage_gauge = Gauge('bot_cpu_usage', 'CPU usage of bots')
        self.mem_usage_gauge = Gauge('bot_mem_usage', 'Memory usage of bots')
        self.system_cpu_gauge = Gauge('system_cpu_usage', 'Overall system CPU usage')
        self.system_mem_gauge = Gauge('system_mem_usage', 'Overall system memory usage')

        start_http_server(8000)
        self._initialize_database()

    def _initialize_database(self):
        """Inicjalizuje bazę danych SQLite do przechowywania logów."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                            timestamp TEXT,
                            event TEXT
                          )''')
        conn.commit()
        conn.close()

    def _log_event(self, event):
        """Zapisuje zdarzenie do bazy danych."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO logs (timestamp, event) VALUES (?, ?)', (time.strftime('%Y-%m-%d %H:%M:%S'), event))
        conn.commit()
        conn.close()

    def _monitor_container(self, bot_name):
        """Monitoruje kontener, dynamicznie dostosowuje CPU i RAM, skaluje system, integracja z Prometheus."""
        container = self.containers.get(bot_name)
        if not container:
            return
        
        while True:
            stats = container.stats(stream=False)
            cpu_usage = stats['cpu_stats']['cpu_usage']['total_usage']
            mem_usage = stats['memory_stats']['usage']
            mem_limit = stats['memory_stats']['limit']
            system_cpu_usage = psutil.cpu_percent()
            system_mem_usage = psutil.virtual_memory().percent
            
            self.load_history.append((cpu_usage, mem_usage, system_cpu_usage, system_mem_usage))
            if len(self.load_history) > 10:
                self.load_history.pop(0)
            
            avg_cpu = sum(x[0] for x in self.load_history) / len(self.load_history)
            avg_mem = sum(x[1] for x in self.load_history) / len(self.load_history)
            avg_system_cpu = sum(x[2] for x in self.load_history) / len(self.load_history)
            avg_system_mem = sum(x[3] for x in self.load_history) / len(self.load_history)

            # Prometheus metrics update
            self.cpu_usage_gauge.set(avg_cpu)
            self.mem_usage_gauge.set(avg_mem)
            self.system_cpu_gauge.set(avg_system_cpu)
            self.system_mem_gauge.set(avg_system_mem)
            
            if avg_mem / mem_limit > 0.8 or avg_system_mem > 85:
                message = f"Zwiększanie zasobów RAM dla kontenera {bot_name}."
                self._send_webhook_alert(message)
                self._log_event(message)
                container.update(mem_limit=str(int(mem_limit * 1.2)))
            
            if avg_cpu > 50000 or avg_system_cpu > 85:
                message = f"Zwiększanie zasobów CPU dla kontenera {bot_name}."
                self._send_webhook_alert(message)
                self._log_event(message)
                container.update(cpu_quota=int(avg_cpu * 1.2))
            
            if avg_mem / mem_limit > 0.9 or avg_cpu > 70000:
                message = f"Restartowanie kontenera {bot_name} z powodu wysokiego zużycia zasobów."
                self._send_webhook_alert(message)
                self._log_event(message)
                container.restart()
            
            if avg_cpu > 60000 or avg_mem / mem_limit > 0.85:
                message = "Skalowanie systemu: dodawanie nowego kontenera."
                self._send_webhook_alert(message)
                self._log_event(message)
                self._scale_up(container.image.tags[0])
            
            time.sleep(5)

    def _send_webhook_alert(self, message):
        """Wysyła powiadomienie webhookiem o stanie systemu."""
        if self.webhook_url:
            try:
                requests.post(self.webhook_url, json={"text": message})
            except Exception as e:
                print(f"Błąd podczas wysyłania webhooka: {e}")task_manager

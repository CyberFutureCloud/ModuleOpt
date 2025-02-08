import docker
import time
import random
import psutil
from prometheus_client import Gauge, start_http_server

class ShadowBotManager:
    def __init__(self, max_bots=5, image_name="shadow_bot_image", cpu_limit=0.5, mem_limit="256m"):
        """
        :param max_bots: Maksymalna liczba jednocześnie działających botów.
        :param image_name: Nazwa obrazu Dockera dla botów.
        :param cpu_limit: Limit CPU dla każdego bota (np. 0.5 oznacza 50% jednego rdzenia).
        :param mem_limit: Limit pamięci RAM dla każdego bota.
        """
        self.docker_client = docker.from_env()
        self.max_bots = max_bots
        self.image_name = image_name
        self.cpu_limit = cpu_limit
        self.mem_limit = mem_limit
        self.bots = {}

        # Prometheus metrics
        self.bot_count_gauge = Gauge('shadow_bot_count', 'Number of running Shadow Bots')
        self.system_cpu_gauge = Gauge('system_cpu_usage', 'Overall system CPU usage')
        self.system_mem_gauge = Gauge('system_mem_usage', 'Overall system memory usage')

        start_http_server(9000)
    
    def create_shadow_bot(self, bot_name=None):
        """Tworzy i uruchamia nowego bota w osobnym kontenerze."""
        if len(self.bots) >= self.max_bots:
            print("Maksymalna liczba botów osiągnięta. Nie można uruchomić kolejnego.")
            return None
        
        bot_name = bot_name or f"shadow_bot_{random.randint(1000, 9999)}"
        container = self.docker_client.containers.run(
            self.image_name,
            name=bot_name,
            detach=True,
            mem_limit=self.mem_limit,
            cpu_quota=int(self.cpu_limit * 100000),
            restart_policy={"Name": "always"}
        )
        self.bots[bot_name] = container
        self.bot_count_gauge.set(len(self.bots))
        print(f"Uruchomiono Shadow Bota: {bot_name}")
        return container
    
    def stop_shadow_bot(self, bot_name):
        """Zatrzymuje i usuwa bota na podstawie jego nazwy."""
        if bot_name in self.bots:
            self.bots[bot_name].remove(force=True)
            del self.bots[bot_name]
            self.bot_count_gauge.set(len(self.bots))
            print(f"Zatrzymano i usunięto bota: {bot_name}")
        else:
            print(f"Bot {bot_name} nie istnieje.")
    
    def list_running_bots(self):
        """Zwraca listę aktualnie działających botów."""
        return list(self.bots.keys())
    
    def auto_scale_bots(self):
        """Automatycznie skaluje liczbę botów w zależności od obciążenia systemu."""
        system_cpu = psutil.cpu_percent()
        system_mem = psutil.virtual_memory().percent
        self.system_cpu_gauge.set(system_cpu)
        self.system_mem_gauge.set(system_mem)
        
        if system_cpu > 80 or system_mem > 80 and len(self.bots) < self.max_bots:
            print("Wysokie obciążenie systemu - dodanie nowego Shadow Bota.")
            self.create_shadow_bot()
        elif system_cpu < 30 and system_mem < 30 and len(self.bots) > 1:
            bot_to_remove = random.choice(self.list_running_bots())
            print(f"Niskie obciążenie systemu - usunięcie Shadow Bota: {bot_to_remove}.")
            self.stop_shadow_bot(bot_to_remove)
        
        print(f"Dostosowano liczbę botów. Aktualna liczba: {len(self.bots)}")

if __name__ == "__main__":
    manager = ShadowBotManager()
    manager.create_shadow_bot()
    time.sleep(10)
    manager.auto_scale_bots()

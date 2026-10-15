"""P7 multiprocessing 多进程：fork/clone syscall，gVisor 已知弱项。"""
import multiprocessing as mp


def child() -> None:
    pass


if __name__ == "__main__":
    p = mp.Process(target=child)
    p.start()
    p.join()
    print("exitcode =", p.exitcode)

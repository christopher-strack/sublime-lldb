
def main():
    import argparse

    from lldbclient.client import LldbClient

    parser = argparse.ArgumentParser()
    parser.add_argument('address')
    args = parser.parse_args()

    with LldbClient(args.address) as client:
        client.listen_forever()


if __name__ == "__main__":
    main()

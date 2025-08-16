declare module 'pg' {
  export class Pool {
    constructor(opts?: any);
    query: (...args: any[]) => Promise<any>;
    connect: () => Promise<any>;
    end: () => Promise<void>;
  }
}

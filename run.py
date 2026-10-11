import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
if __name__=='__main__':
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=int(os.environ.get('PORT','8082')),workers=1)
